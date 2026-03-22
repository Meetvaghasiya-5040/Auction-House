from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import csv

from bids.models import PendingPayment, AdminWallet, SecurityDeposit
from auction_list.models import Invoice, Lot

@staff_member_required
def admin_finance(request):
    """
    Finance dashboard showing pending payments, admin wallet, deposits, and recent invoices.
    """
    admin_wallet = AdminWallet.load()
    pending_payments = PendingPayment.objects.filter(status__in=['pending', 'expired']).order_by('-created_at')[:50]
    deposits = SecurityDeposit.objects.all().order_by('-created_at')[:50]
    recent_invoices = Invoice.objects.all().order_by('-issued_at')[:50]
    
    # Calculate stats
    pending_count = PendingPayment.objects.filter(status='pending').count()
    active_deposits = SecurityDeposit.objects.filter(status='active').count()
    
    context = {
        'wallet': admin_wallet,
        'pending_payments': pending_payments,
        'deposits': deposits,
        'recent_invoices': recent_invoices,
        'pending_count': pending_count,
        'active_deposits': active_deposits,
    }
    
    return render(request, 'admin_panel/finance.html', context)


@staff_member_required
def admin_finance_report(request):
    """Generates a CSV report of recent financial transactions and metrics."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="finance_report_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    
    # Write Overview
    writer.writerow(['--- Financial Overview ---'])
    admin_wallet = AdminWallet.load()
    active_deposits_count = SecurityDeposit.objects.filter(status='active').count()
    pending_payments_count = PendingPayment.objects.filter(status='pending').count()
    
    writer.writerow(['Admin Wallet Balance', f'Rs. {admin_wallet.balance}'])
    writer.writerow(['Active Security Deposits', active_deposits_count])
    writer.writerow(['Pending Buyer Payments', pending_payments_count])
    writer.writerow([])
    
    # Write Recent Invoices
    writer.writerow(['--- Recent Successful Invoices ---'])
    writer.writerow(['Invoice ID', 'Date', 'User', 'Lot', 'Amount', 'Status'])
    
    invoices = Invoice.objects.select_related('user', 'lot').order_by('-issued_at')[:100]
    for inv in invoices:
        writer.writerow([
            inv.invoice_number,
            inv.issued_at.strftime("%Y-%m-%d %H:%M:%S"),
            inv.user.username,
            inv.lot.title,
            inv.amount,
            inv.status
        ])
        
    writer.writerow([])
    
    # Write Recent Deposits
    writer.writerow(['--- Recent Security Deposits ---'])
    writer.writerow(['Date', 'User', 'Transaction ID', 'Amount', 'Status'])
    
    deposits = SecurityDeposit.objects.select_related('user').order_by('-created_at')[:100]
    for dep in deposits:
        writer.writerow([
            dep.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            dep.user.username,
            dep.razorpay_payment_id,
            dep.amount,
            dep.status
        ])
        
    return response


@staff_member_required
def admin_download_invoice(request, invoice_id):
    """Generates and serves the PDF for a specific invoice."""
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    from bids.invoice_generator import generate_invoice
    import os
    
    try:
        pdf_path = generate_invoice(invoice.lot, invoice.user)
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as pdf_file:
                response = HttpResponse(pdf_file.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                return response
        else:
            messages.error(request, "Failed to locate invoice PDF.")
    except Exception as e:
        messages.error(request, f"Error generating invoice: {e}")
        
    return redirect('admin_panel:finance')


@staff_member_required
@require_POST
def admin_force_payment(request, payment_id):
    """Force completes a pending payment for a lot, skipping Razorpay."""
    payment = get_object_or_404(PendingPayment, id=payment_id)
    lot = payment.lot
    
    if payment.status == 'completed':
        return JsonResponse({'success': False, 'error': 'Payment is already completed.'})
        
    try:
        with transaction.atomic():
            # 1. Update Payment Record
            payment.status = 'completed'
            payment.pin_verified = True
            payment.save()
            
            winning_amount = Decimal(str(lot.current_bid))
            
            # 2. Check Real Estate vs Standard
            is_real_estate = hasattr(lot, 'lot_catagory') and lot.lot_catagory and getattr(lot.lot_catagory, 'is_immovable', False)
            
            if is_real_estate:
                # Real Estate Flow (PropertySale)
                from auction_list.models import PropertySale
                
                lot.status = 'property_sale'
                lot.save()
                
                seller_item = lot.items.first()
                seller_user = seller_item.owner if seller_item else lot.winning_bidder
                
                PropertySale.objects.create(
                    lot=lot,
                    buyer=payment.user,
                    seller=seller_user,
                    status='emd_paid',
                    emd_percentage=Decimal('5.00'),
                    emd_amount=payment.amount_to_pay,
                    emd_paid=True,
                    emd_payment_id='ADMIN_FORCED',
                    emd_deadline=timezone.now(),
                    final_amount=winning_amount - payment.amount_to_pay,
                    platform_commission_pct=Decimal('2.00')
                )
                
                for item in lot.items.all():
                    item.status = 'Sold'
                    item.save(update_fields=['status'])
                    
                # Admin gets Buyer Premium
                buyer_premium_pct = Decimal(str(lot.auction.buyer_premium_percentage or 0))
                buyer_premium_amount = (winning_amount * buyer_premium_pct / Decimal('100')).quantize(Decimal('0.01'))
                
                if buyer_premium_amount > 0:
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(
                        amount=buyer_premium_amount,
                        description=f"Buyer Premium (Admin Forced) for Lot #{lot.lot_number}"
                    )
                    
            else:
                # Standard Delivery Flow
                lot.status = 'paid'
                lot.save()
                
                from auction_list.models import Delivery
                delivery, created = Delivery.objects.get_or_create(lot=lot)
                if created:
                    delivery.generate_otp()
                delivery.status = 'pending'
                delivery.save()
                
                for item in lot.items.all():
                    item.status = 'Sold'
                    item.save(update_fields=['status'])
                    
                # Admin gets Buyer Premium
                buyer_premium_pct = Decimal(str(lot.auction.buyer_premium_percentage or 0))
                buyer_premium_amount = (winning_amount * buyer_premium_pct / Decimal('100')).quantize(Decimal('0.01'))
                
                if buyer_premium_amount > 0:
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(
                        amount=buyer_premium_amount,
                        description=f"Buyer Premium (Admin Forced) for Lot #{lot.lot_number}"
                    )
                    
            # 3. Update Invoice to Paid
            try:
                invoice = Invoice.objects.get(lot=lot, user=payment.user)
                invoice.status = 'paid'
                invoice.save(update_fields=['status'])
                
                from auction_list.models import send_invoice_email_task
                send_invoice_email_task(invoice.id)
            except Invoice.DoesNotExist:
                pass
                
        return JsonResponse({'success': True, 'message': f'Payment for Lot {lot.title} forced successfully.'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
