from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from decimal import Decimal
import json
import razorpay
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def broadcast_property_sale_update(property_sale, message=""):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'admin_updates',
        {
            'type': 'global_model_update',
            'data': {
                'type': 'property_sale_update',
                'sale_id': property_sale.id,
                'status': property_sale.status,
                'message': message
            }
        }
    )
    async_to_sync(channel_layer.group_send)(
        'global_status',
        {
            'type': 'global_model_update',
            'data': {
                'model': 'PropertySale',
                'pk': property_sale.id,
                'action': 'update',
                'fields': {
                    'status': property_sale.status,
                    'status_display': property_sale.get_status_display(),
                }
            }
        }
    )

def send_property_agreement_email(property_sale, pdf_content):
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.conf import settings
    
    subject = f"Action Required: Property Sale Agreement for Lot #{property_sale.lot.lot_number}"
    context = {
        'buyer': property_sale.buyer,
        'lot_title': property_sale.lot.title,
        'lot_number': property_sale.lot.lot_number,
    }
    text_content = f"The sale agreement for {property_sale.lot.title} is ready. Please log in to sign it."
    
    try:
        html_content = render_to_string('auctions/emails/property_agreement_email.html', context)
    except:
        html_content = None

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easybid.com'),
        to=[property_sale.buyer.email],
    )
    if html_content:
        msg.attach_alternative(html_content, "text/html")
        
    # Attach the generated PDF agreement
    msg.attach(f"Agreement_Lot_{property_sale.lot.lot_number}.pdf", pdf_content, "application/pdf")
        
    try:
        msg.send(fail_silently=False)
        print(f"Agreement email sent to {property_sale.buyer.email}")
    except Exception as e:
        print(f"Failed to send agreement email: {e}")

def send_property_step_email(property_sale, step_name):
    from django.core.mail import send_mail
    from django.conf import settings
    
    lot = property_sale.lot
    buyer = property_sale.buyer
    seller = property_sale.seller
    
    buyer_subject = f"Update on your purchase: Lot #{lot.lot_number}"
    seller_subject = f"Update on your sale: Lot #{lot.lot_number}"
    
    buyer_msg = ""
    seller_msg = ""
    
    if step_name == 'emd_paid':
        buyer_msg = f"Your EMD payment for '{lot.title}' is confirmed. Please log in to upload your KYC documents."
        seller_msg = f"The buyer has paid the EMD for '{lot.title}'. Please log in to upload the property documents."
    elif step_name == 'documents_verified':
        buyer_msg = f"Documents for '{lot.title}' have been verified. The sale agreement is being prepared."
        seller_msg = f"Documents for '{lot.title}' have been verified. The sale agreement is being prepared."
    elif step_name == 'agreement_pending':
        buyer_msg = f"The sale agreement for '{lot.title}' is ready. Please log in to review and sign it."
        seller_msg = f"The sale agreement for '{lot.title}' is ready. Please log in to review and sign it."
    elif step_name == 'agreement_signed':
        buyer_msg = f"The agreement for '{lot.title}' is fully signed. Please log in to pay the final amount."
        seller_msg = f"The agreement for '{lot.title}' is fully signed. Waiting for the buyer's final payment."
    elif step_name == 'final_payment_done':
        buyer_msg = f"Your final payment for '{lot.title}' is confirmed. The admin will now begin the registration process."
        seller_msg = f"The buyer made the final payment for '{lot.title}'. The admin will begin property registration."
    elif step_name == 'registration_done':
        buyer_msg = f"The property '{lot.title}' is registered in your name. Please log in to download the sale deed."
        seller_msg = f"The property '{lot.title}' is registered to the new owner. Please coordinate possession."
    elif step_name == 'possession_transferred':
        buyer_msg = f"Possession confirmed for '{lot.title}'. The transaction is complete!"
        seller_msg = f"Possession confirmed for '{lot.title}'. Your seller funds will be released shortly."
        
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easybid.com')
        if buyer_msg:
            send_mail(buyer_subject, buyer_msg, from_email, [buyer.email], fail_silently=False)
        if seller_msg:
            send_mail(seller_subject, seller_msg, from_email, [seller.email], fail_silently=False)
    except Exception as e:
        import traceback
        print(f"Failed to send property step email ({step_name}): {e}")
        traceback.print_exc()

from auction_list.models import Lot, PropertySale, Invoice

razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


def is_admin(user):
    return user.is_staff


# ─────────────────────────────────────────────────────────────
# 1. PROPERTY SALE DASHBOARD (Main Tracking Page)
# ─────────────────────────────────────────────────────────────

@login_required
def property_sale_dashboard(request, lot_id):
    """Main tracking page for buyer/seller/admin showing the current step"""
    lot = get_object_or_404(Lot, id=lot_id)
    property_sale = get_object_or_404(PropertySale, lot=lot)
    
    # Only buyer, seller, or admin can access
    user = request.user
    if not (user == property_sale.buyer or user == property_sale.seller or user.is_staff):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('home')
    
    # Collect item document proofs (uploaded by seller via item page)
    items = lot.items.all()
    item_seller_docs = []
    for item in items:
        if item.document_proofs:
            for doc in item.document_proofs:
                if doc not in item_seller_docs:
                    item_seller_docs.append(doc)
    
    # Combined seller docs = property sale uploads + item page uploads
    all_seller_docs = list(property_sale.seller_documents or []) + item_seller_docs
    
    # Auto-fix status: if both buyer docs and seller docs exist but status hasn't advanced
    if property_sale.status in ('emd_paid', 'documents_pending'):
        has_buyer = bool(property_sale.buyer_documents)
        has_seller = bool(all_seller_docs)
        if has_buyer and has_seller:
            property_sale.status = 'documents_submitted'
            property_sale.save()
        elif has_buyer or has_seller:
            if property_sale.status == 'emd_paid':
                property_sale.status = 'documents_pending'
                property_sale.save()
    
    # Determine what the user can do at each step
    context = {
        'lot': lot,
        'sale': property_sale,
        'items': items,
        'is_buyer': user == property_sale.buyer,
        'is_seller': user == property_sale.seller,
        'is_admin': user.is_staff,
        'progress': property_sale.get_progress_percentage(),
        'step': property_sale.get_status_step_number(),
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'item_seller_docs': item_seller_docs,
        'all_seller_docs': all_seller_docs,
    }
    
    return render(request, 'auctions/property_sale_dashboard.html', context)


# ─────────────────────────────────────────────────────────────
# 2. DOCUMENT SUBMISSION (Buyer & Seller)
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def submit_documents(request, lot_id):
    """Buyer or Seller uploads KYC + property documents"""
    lot = get_object_or_404(Lot, id=lot_id)
    property_sale = get_object_or_404(PropertySale, lot=lot)
    
    user = request.user
    doc_type = request.POST.get('doc_type')  # 'buyer' or 'seller'
    
    if doc_type == 'buyer' and user != property_sale.buyer:
        return JsonResponse({'success': False, 'error': 'Only the buyer can submit buyer documents.'})
    if doc_type == 'seller' and user != property_sale.seller:
        return JsonResponse({'success': False, 'error': 'Only the seller can submit seller documents.'})
    
    # Handle file uploads (store as Cloudinary URLs or local paths)
    uploaded_files = request.FILES.getlist('documents')
    if not uploaded_files:
        return JsonResponse({'success': False, 'error': 'No files uploaded.'})
    
    from django.core.files.storage import default_storage
    
    file_paths = []
    for f in uploaded_files:
        path = default_storage.save(f'property_docs/{lot_id}/{doc_type}/{f.name}', f)
        url = default_storage.url(path)
        file_paths.append(url)
    
    # Append to existing documents
    if doc_type == 'buyer':
        existing = property_sale.buyer_documents or []
        property_sale.buyer_documents = existing + file_paths
    else:
        existing = property_sale.seller_documents or []
        property_sale.seller_documents = existing + file_paths
    
    # Check if seller has docs (either through property sale upload or item page)
    seller_item = lot.items.first()
    has_seller_docs = bool(property_sale.seller_documents)
    if not has_seller_docs and seller_item and seller_item.document_proofs:
        has_seller_docs = True
    
    # Update status if both have submitted
    if property_sale.status == 'emd_paid':
        property_sale.status = 'documents_pending'
    
    # If both buyer and seller have docs, mark as submitted
    if property_sale.buyer_documents and has_seller_docs:
        property_sale.status = 'documents_submitted'
    
    property_sale.save()
    
    # Trigger real-time update in admin and user panels
    broadcast_property_sale_update(property_sale, f'{doc_type.title()} documents uploaded')
    
    return JsonResponse({
        'success': True,
        'message': f'{doc_type.title()} documents uploaded successfully.',
        'files': file_paths,
    })


# ─────────────────────────────────────────────────────────────
# 3. ADMIN DOCUMENT VERIFICATION
# ─────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_verify_documents(request, sale_id):
    """Admin approves or rejects submitted documents"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    action = request.POST.get('action')  # 'approve' or 'reject'
    reason = request.POST.get('reason', '')
    
    if action == 'approve':
        property_sale.status = 'documents_verified'
        property_sale.documents_verified_by = request.user
        property_sale.documents_verified_at = timezone.now()
        property_sale.documents_rejection_reason = ''
        property_sale.save()
        broadcast_property_sale_update(property_sale, "Documents verified")
        send_property_step_email(property_sale, 'documents_verified')
        
        messages.success(request, f"Documents verified for Lot #{property_sale.lot.lot_number}.")
    elif action == 'reject':
        property_sale.status = 'documents_pending'
        property_sale.documents_rejection_reason = reason
        property_sale.save()
        broadcast_property_sale_update(property_sale, "Documents rejected")
        
        messages.warning(request, f"Documents rejected. Reason sent to buyer/seller.")
    else:
        messages.error(request, "Invalid action.")
    
    return redirect('property_sale_dashboard', lot_id=property_sale.lot.id)


# ─────────────────────────────────────────────────────────────
# 4. GENERATE AGREEMENT
# ─────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def generate_agreement(request, sale_id):
    """Auto-generate a sale agreement PDF"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    if property_sale.status not in ('documents_verified', 'agreement_pending'):
        messages.error(request, "Documents must be verified before generating agreement.")
        return redirect('property_sale_dashboard', lot_id=property_sale.lot.id)
    
    # Generate agreement context
    lot = property_sale.lot
    items = lot.items.all()
    
    context = {
        'sale': property_sale,
        'lot': lot,
        'items': items,
        'buyer': property_sale.buyer,
        'seller': property_sale.seller,
        'winning_bid': lot.current_bid,
        'emd_amount': property_sale.emd_amount,
        'remaining_amount': property_sale.remaining_amount,
        'agreement_date': timezone.now().strftime("%B %d, %Y"),
        'agreement_number': f"AGR-{lot.id}-{uuid.uuid4().hex[:8].upper()}",
    }
    
    # Render the agreement HTML template
    from django.template.loader import render_to_string
    agreement_html = render_to_string('auctions/property_sale_agreement.html', context)
    
    try:
        from io import BytesIO
        from xhtml2pdf import pisa
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(agreement_html, dest=pdf_buffer)
        
        if not pisa_status.err:
            pdf_content = pdf_buffer.getvalue()
            pdf_path = f'property_agreements/AGR-{lot.id}.pdf'
            
            # Save file via storage
            saved_path = default_storage.save(pdf_path, ContentFile(pdf_content))
            property_sale.agreement_file = default_storage.url(saved_path)
            
            # Email the document to the buyer
            send_property_agreement_email(property_sale, pdf_content)
            
        pdf_buffer.close()
    except Exception as e:
        print(f"PDF generation failed: {e}")
        # Fallback: store just the agreement number
        property_sale.agreement_file = f"AGR-{lot.id}-{uuid.uuid4().hex[:8].upper()}"
    
    property_sale.status = 'agreement_pending'
    property_sale.save()
    broadcast_property_sale_update(property_sale, "Agreement generated")
    send_property_step_email(property_sale, 'agreement_pending')
    
    messages.success(request, "Sale agreement generated. Awaiting signatures from buyer and seller.")
    return redirect('property_sale_dashboard', lot_id=lot.id)


# ─────────────────────────────────────────────────────────────
# 5. SIGN AGREEMENT (Buyer / Seller)
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def sign_agreement(request, sale_id):
    """Buyer or Seller signs the agreement"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    user = request.user
    
    if property_sale.status != 'agreement_pending':
        return JsonResponse({'success': False, 'error': 'Agreement is not pending signature.'})
    
    if user == property_sale.buyer:
        property_sale.buyer_agreed = True
    elif user == property_sale.seller:
        property_sale.seller_agreed = True
    else:
        return JsonResponse({'success': False, 'error': 'Only buyer or seller can sign.'})
    
    # If both signed, move to next step
    if property_sale.buyer_agreed and property_sale.seller_agreed:
        property_sale.status = 'agreement_signed'
        property_sale.agreement_signed_at = timezone.now()
        send_property_step_email(property_sale, 'agreement_signed')
    
    property_sale.save()
    broadcast_property_sale_update(property_sale, "Agreement signed")
    
    return JsonResponse({
        'success': True,
        'message': 'Agreement signed successfully.',
        'both_signed': property_sale.buyer_agreed and property_sale.seller_agreed,
    })


# ─────────────────────────────────────────────────────────────
# 6. INITIATE FINAL PAYMENT (Razorpay Order)
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def initiate_final_payment(request, sale_id):
    """Create Razorpay order for the remaining amount"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    if request.user != property_sale.buyer:
        return JsonResponse({'success': False, 'error': 'Only the buyer can make this payment.'})
    
    if property_sale.status not in ('agreement_signed', 'final_payment_pending'):
        return JsonResponse({'success': False, 'error': 'Agreement must be signed by both parties first.'})
    
    property_sale.status = 'final_payment_pending'
    property_sale.save()
    
    amount = property_sale.final_amount
    amount_in_paise = int(amount * 100)
    
    # Bypass Razorpay order generation if too large and in debug mode
    # Razorpay Test Mode limit is usually ₹5,00,000 (50,000,000 paise)
    if settings.DEBUG and amount_in_paise > 50000000:
        return JsonResponse({
            'success': True,
            'simulated': True,
            'message': 'Simulated order created for local testing.'
        })
    
    try:
        razorpay_order = razorpay_client.order.create({
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f'property_final_{property_sale.lot.id}_{property_sale.id}'
        })
        
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'amount': amount_in_paise,
            'currency': 'INR',
            'lot_title': property_sale.lot.title,
            'total_amount_formatted': f"{amount:,.2f}",
            'user_name': request.user.get_full_name() or request.user.username,
            'user_email': request.user.email,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Error creating payment order: {str(e)}'})


# ─────────────────────────────────────────────────────────────
# 7. VERIFY FINAL PAYMENT
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def verify_final_payment(request, sale_id):
    """Verify Razorpay payment for the final amount"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    if request.user != property_sale.buyer:
        return JsonResponse({'success': False, 'error': 'Unauthorized.'}, status=403)
    
    data = json.loads(request.body)
    
    # Check if simulated (for local dev with large amounts)
    if settings.DEBUG and data.get('simulated'):
        razorpay_payment_id = data.get('razorpay_payment_id', f'pay_simulated_{uuid.uuid4().hex[:8]}')
    else:
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })
        except Exception:
            return JsonResponse({'success': False, 'error': 'Payment verification failed.'}, status=400)
    
    with transaction.atomic():
        property_sale.status = 'final_payment_done'
        property_sale.final_payment_id = razorpay_payment_id
        property_sale.final_payment_at = timezone.now()
        property_sale.save()
        broadcast_property_sale_update(property_sale, "Final payment done")
        send_property_step_email(property_sale, 'final_payment_done')
        
        # Update invoice if exists
        try:
            invoice = Invoice.objects.get(lot=property_sale.lot, user=request.user)
            invoice.status = 'paid'
            invoice.save()
        except Invoice.DoesNotExist:
            pass
    
    return JsonResponse({
        'success': True,
        'message': 'Final payment completed successfully! Proceed to property registration.',
    })


# ─────────────────────────────────────────────────────────────
# 8. UPDATE REGISTRATION (Admin)
# ─────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
@require_POST
def update_registration(request, sale_id):
    """Admin enters registration number, stamp duty, and uploads sale deed"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    if property_sale.status not in ('final_payment_done', 'registration_pending'):
        messages.error(request, "Final payment must be completed first.")
        return redirect('property_sale_dashboard', lot_id=property_sale.lot.id)
    
    registration_number = request.POST.get('registration_number', '')
    stamp_duty = request.POST.get('stamp_duty', '0')
    registration_charges = request.POST.get('registration_charges', '0')
    
    property_sale.registration_number = registration_number
    property_sale.stamp_duty = Decimal(stamp_duty) if stamp_duty else Decimal('0')
    property_sale.registration_charges = Decimal(registration_charges) if registration_charges else Decimal('0')
    property_sale.registration_date = timezone.now()
    
    # Handle sale deed upload
    if 'sale_deed' in request.FILES:
        from django.core.files.storage import default_storage
        f = request.FILES['sale_deed']
        path = default_storage.save(f'sale_deeds/{property_sale.lot.id}/{f.name}', f)
        property_sale.sale_deed_file = default_storage.url(path)
    
    property_sale.status = 'registration_done'
    property_sale.save()
    broadcast_property_sale_update(property_sale, "Registration completed")
    send_property_step_email(property_sale, 'registration_done')
    
    messages.success(request, f"Property registration recorded for Lot #{property_sale.lot.lot_number}.")
    return redirect('property_sale_dashboard', lot_id=property_sale.lot.id)


# ─────────────────────────────────────────────────────────────
# 9. CONFIRM POSSESSION (Admin/Seller)
# ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def confirm_possession(request, sale_id):
    """Confirm possession transfer → mark lot as sold → release funds"""
    property_sale = get_object_or_404(PropertySale, id=sale_id)
    
    user = request.user
    if not (user.is_staff or user == property_sale.seller):
        return JsonResponse({'success': False, 'error': 'Only admin or seller can confirm possession.'})
    
    if property_sale.status != 'registration_done':
        return JsonResponse({'success': False, 'error': 'Registration must be completed first.'})
    
    # Handle possession letter upload
    if 'possession_letter' in request.FILES:
        from django.core.files.storage import default_storage
        f = request.FILES['possession_letter']
        path = default_storage.save(f'possession_letters/{property_sale.lot.id}/{f.name}', f)
        property_sale.possession_letter_file = default_storage.url(path)
    
    with transaction.atomic():
        property_sale.status = 'possession_transferred'
        property_sale.possession_date = timezone.now()
        property_sale.save()
        
        # Mark lot as sold
        lot = property_sale.lot
        lot.status = 'sold'
        lot.save()
        
        # Update all items as delivered
        for item in lot.items.all():
            item.pickup_status = 'delivered'
            item.save(update_fields=['pickup_status'])
        
        # ── Release Funds to Seller ──
        from bids.utils import release_seller_funds
        release_seller_funds(lot)
        
        # Mark as completed
        property_sale.status = 'completed'
        property_sale.save()
        broadcast_property_sale_update(property_sale, "Possession confirmed and sale completed")
        send_property_step_email(property_sale, 'possession_transferred')
        
        # Broadcast status change
        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(lot)
    
    return JsonResponse({
        'success': True,
        'message': 'Possession confirmed! Property sale completed. Funds released to seller.',
    })


# ─────────────────────────────────────────────────────────────
# ADMIN: Property Sales List View
# ─────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def admin_property_sales(request):
    """Admin view to see all property sales in progress"""
    sales = PropertySale.objects.select_related(
        'lot', 'lot__auction', 'buyer', 'seller'
    ).order_by('-created_at')
    
    context = {
        'sales': sales,
        'active_count': sales.exclude(status='completed').count(),
        'completed_count': sales.filter(status='completed').count(),
    }
    return render(request, 'auctions/admin_property_sales.html', context)
