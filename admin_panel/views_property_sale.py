from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone
from auction_list.models import PropertySale, Lot
from decimal import Decimal
import json


@staff_member_required
def admin_property_sales(request):
    """Admin dashboard for managing all property sales."""
    
    sales = PropertySale.objects.select_related(
        'lot', 'lot__auction', 'lot__lot_catagory', 'buyer', 'seller'
    ).order_by('-created_at')
    
    # Filter by status tab
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'active':
        sales = sales.exclude(status__in=['completed', 'possession_transferred'])
    elif status_filter == 'completed':
        sales = sales.filter(status__in=['completed', 'possession_transferred'])
    elif status_filter == 'docs_review':
        sales = sales.filter(status__in=['documents_pending', 'documents_submitted'])
    elif status_filter == 'payment':
        sales = sales.filter(status__in=['agreement_signed', 'final_payment_pending', 'final_payment_done'])
    elif status_filter == 'registration':
        sales = sales.filter(status__in=['registration_pending', 'registration_done'])
    
    # Stats
    all_sales = PropertySale.objects.all()
    stats = {
        'total': all_sales.count(),
        'active': all_sales.exclude(status__in=['completed', 'possession_transferred']).count(),
        'docs_review': all_sales.filter(status__in=['documents_pending', 'documents_submitted']).count(),
        'completed': all_sales.filter(status__in=['completed', 'possession_transferred']).count(),
        'total_value': sum(s.lot.current_bid for s in all_sales if s.lot.current_bid) or 0,
    }
    
    context = {
        'sales': sales,
        'stats': stats,
        'status_filter': status_filter,
    }
    return render(request, 'admin_panel/property_sales.html', context)


@staff_member_required
def admin_property_sale_detail(request, sale_id):
    """API endpoint returning property sale detail as JSON for the modal."""
    sale = get_object_or_404(
        PropertySale.objects.select_related('lot', 'buyer', 'seller'),
        id=sale_id
    )
    
    # Collect item docs (seller's item-page uploads)
    item_docs = []
    for item in sale.lot.items.all():
        if item.document_proofs:
            item_docs.extend(item.document_proofs)
    
    all_seller_docs = list(sale.seller_documents or []) + item_docs
    
    data = {
        'id': sale.id,
        'lot_id': sale.lot.id,
        'lot_number': sale.lot.lot_number,
        'lot_title': sale.lot.title,
        'status': sale.status,
        'status_display': sale.get_status_display(),
        'buyer': sale.buyer.get_full_name() or sale.buyer.username,
        'buyer_email': sale.buyer.email,
        'seller': sale.seller.get_full_name() or sale.seller.username,
        'seller_email': sale.seller.email,
        'winning_bid': str(sale.lot.current_bid),
        'emd_amount': str(sale.emd_amount),
        'emd_paid': sale.emd_paid,
        'emd_payment_id': sale.emd_payment_id or '',
        'remaining_amount': str(sale.remaining_amount),
        'commission_pct': str(sale.platform_commission_pct),
        'buyer_documents': sale.buyer_documents or [],
        'seller_documents': all_seller_docs,
        'documents_verified': sale.status in ('documents_verified', 'agreement_pending', 'agreement_signed',
                                               'final_payment_pending', 'final_payment_done',
                                               'registration_pending', 'registration_done',
                                               'possession_transferred', 'completed'),
        'agreement_file': sale.agreement_file or '',
        'buyer_agreed': sale.buyer_agreed,
        'seller_agreed': sale.seller_agreed,
        'final_payment_id': sale.final_payment_id or '',
        'registration_number': sale.registration_number or '',
        'possession_date': sale.possession_date.strftime('%b %d, %Y') if sale.possession_date else '',
        'created_at': sale.created_at.strftime('%b %d, %Y %H:%M'),
        'step': sale.get_status_step_number(),
        'progress': sale.get_progress_percentage(),
        'dashboard_url': f'/auctions/auctions/property-sale/{sale.lot.id}/',
    }
    return JsonResponse(data)


@staff_member_required
@require_POST
def admin_verify_docs(request, sale_id):
    """Admin verifies or rejects documents from the admin panel."""
    sale = get_object_or_404(PropertySale, id=sale_id)
    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    
    action = data.get('action')
    reason = data.get('reason', '')
    
    if action == 'approve':
        sale.status = 'documents_verified'
        sale.documents_verified_by = request.user
        sale.documents_verified_at = timezone.now()
        sale.documents_rejection_reason = ''
        sale.save()
        return JsonResponse({'success': True, 'message': f'Documents verified for Lot #{sale.lot.lot_number}.'})
    elif action == 'reject':
        sale.status = 'documents_pending'
        sale.documents_rejection_reason = reason
        sale.save()
        return JsonResponse({'success': True, 'message': f'Documents rejected for Lot #{sale.lot.lot_number}.'})
    
    return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)


@staff_member_required
@require_POST
def admin_generate_agreement(request, sale_id):
    """Admin generates agreement from admin panel."""
    from auction_list.views_property_sale import generate_agreement
    # Reuse the existing view logic
    sale = get_object_or_404(PropertySale, id=sale_id)
    if sale.status not in ('documents_verified', 'agreement_pending'):
        return JsonResponse({'success': False, 'error': 'Documents must be verified first.'}, status=400)
    
    # Call the existing generate_agreement logic inline
    import uuid
    from django.conf import settings
    lot = sale.lot
    
    context = {
        'sale': sale,
        'lot': lot,
        'items': lot.items.all(),
        'buyer': sale.buyer,
        'seller': sale.seller,
        'winning_bid': lot.current_bid,
        'emd_amount': sale.emd_amount,
        'remaining_amount': sale.remaining_amount,
        'agreement_date': timezone.now().strftime("%B %d, %Y"),
        'agreement_number': f"AGR-{lot.id}-{uuid.uuid4().hex[:8].upper()}",
    }
    
    from django.template.loader import render_to_string
    agreement_html = render_to_string('auctions/property_sale_agreement.html', context)
    
    try:
        from io import BytesIO
        from xhtml2pdf import pisa
        from django.core.files.storage import default_storage
        
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(agreement_html, dest=pdf_buffer)
        
        if not pisa_status.err:
            pdf_content = pdf_buffer.getvalue()
            pdf_path = f'property_agreements/AGR-{lot.id}.pdf'
            saved_path = default_storage.save(pdf_path, BytesIO(pdf_content))
            sale.agreement_file = default_storage.url(saved_path)
        pdf_buffer.close()
    except Exception as e:
        sale.agreement_file = f"AGR-{lot.id}-{uuid.uuid4().hex[:8].upper()}"
    
    sale.status = 'agreement_pending'
    sale.save()
    
    return JsonResponse({'success': True, 'message': 'Agreement generated successfully.'})


@staff_member_required
@require_POST
def admin_update_registration(request, sale_id):
    """Admin updates registration details from admin panel."""
    sale = get_object_or_404(PropertySale, id=sale_id)
    
    if sale.status not in ('final_payment_done', 'registration_pending'):
        return JsonResponse({'success': False, 'error': 'Final payment must be completed first.'}, status=400)
    
    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    
    sale.registration_number = data.get('registration_number', '')
    sale.stamp_duty = Decimal(data.get('stamp_duty', '0') or '0')
    sale.registration_charges = Decimal(data.get('registration_charges', '0') or '0')
    sale.registration_date = timezone.now()
    sale.status = 'registration_done'
    sale.save()
    
    return JsonResponse({'success': True, 'message': f'Registration recorded for Lot #{sale.lot.lot_number}.'})


@staff_member_required
@require_POST
def admin_confirm_possession(request, sale_id):
    """Admin confirms possession transfer."""
    sale = get_object_or_404(PropertySale, id=sale_id)
    
    if sale.status != 'registration_done':
        return JsonResponse({'success': False, 'error': 'Registration must be completed first.'}, status=400)
    
    with transaction.atomic():
        sale.status = 'possession_transferred'
        sale.possession_date = timezone.now()
        sale.save()
        
        lot = sale.lot
        lot.status = 'sold'
        lot.save()
        
        for item in lot.items.all():
            item.pickup_status = 'delivered'
            item.save(update_fields=['pickup_status'])
        
        from bids.utils import release_seller_funds
        release_seller_funds(lot)
        
        from bids.models import AdminWallet
        winning_amount = Decimal(str(lot.current_bid))
        commission = (winning_amount * sale.platform_commission_pct / Decimal('100')).quantize(Decimal('0.01'))
        admin_wallet = AdminWallet.load()
        admin_wallet.add_funds(
            amount=commission,
            description=f"Property Sale Commission ({sale.platform_commission_pct}%) for Lot #{lot.lot_number}: {lot.title}"
        )
        
        sale.status = 'completed'
        sale.save()
        
        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(lot)
    
    return JsonResponse({'success': True, 'message': 'Possession confirmed! Sale completed. Funds released.'})
