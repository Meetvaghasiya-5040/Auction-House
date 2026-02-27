import razorpay
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from decimal import Decimal
from .models import Wallet, Bid, Transaction, PendingPayment, SecurityDeposit
from auction_list.models import Lot, Invoice

razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


@login_required
def wallet_dashboard(request):
    """Display user's wallet and deposit dashboard"""
    from django.db.models import Sum
    
    # Wallet & Transactions
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-timestamp')[:5]
    total_spent = Transaction.objects.filter(
        wallet=wallet, 
        amount__lt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Make spent amount positive for display
    total_spent = abs(total_spent)
    
    # Security Deposit
    deposit, created = SecurityDeposit.objects.get_or_create(user=request.user)
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'total_spent': total_spent,
        'deposit': deposit,
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
    }
    return render(request, 'bids/wallet_dashboard.html', context)

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

@login_required
@require_POST
def create_deposit_order(request):
    """Create Razorpay order for Security Deposit"""
    deposit, created = SecurityDeposit.objects.get_or_create(user=request.user)
    if deposit.status == 'active':
        return JsonResponse({'success': False, 'error': 'Deposit already active.'})
        
    amount = int(deposit.amount) * 100 # amount in paise
    currency = "INR"
    
    try:
        razorpay_order = razorpay_client.order.create(dict(amount=amount, currency=currency, receipt=f"deposit_{deposit.id}"))
        deposit.razorpay_order_id = razorpay_order['id']
        deposit.status = 'pending'
        deposit.save()
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'amount': amount,
            'currency': currency,
            'key': settings.RAZORPAY_KEY_ID,
            'user_name': request.user.get_full_name() or request.user.username,
            'user_email': request.user.email
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@login_required
@require_POST
def verify_deposit(request):
    import json
    data = json.loads(request.body)
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
        
        deposit = SecurityDeposit.objects.get(user=request.user, razorpay_order_id=razorpay_order_id)
        deposit.razorpay_payment_id = razorpay_payment_id
        deposit.status = 'active'
        deposit.save()
        
        return JsonResponse({'success': True, 'message': 'Security deposit active! You can now bid.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Payment verification failed.'})


@login_required
def add_funds(request):
    """Add funds to user's wallet (Now handled mostly via Razorpay, but keep rendering the page)"""
    if request.method == 'POST':
        # Verify PIN (Removed for Razorpay flow)
        pass
    
    return render(request, 'bids/add_funds.html')

@login_required
@require_POST
def create_wallet_add_funds_order(request):
    """Create Razorpay order for adding funds to Wallet"""
    import json
    data = json.loads(request.body)
    amount = int(Decimal(str(data.get('amount', 0))) * 100) # strictly convert to paise
    
    if amount <= 0:
        return JsonResponse({'success': False, 'error': 'Invalid amount.'})
        
    currency = "INR"
    
    try:
        razorpay_order = razorpay_client.order.create(dict(amount=amount, currency=currency, receipt=f"addfunds_{request.user.id}"))
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'amount': amount,
            'currency': currency,
            'key': settings.RAZORPAY_KEY_ID,
            'user_name': request.user.get_full_name() or request.user.username,
            'user_email': request.user.email
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@login_required
@require_POST
def verify_wallet_add_funds(request):
    import json
    data = json.loads(request.body)
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    amount_paise = data.get('amount') # we need to know how much to add
    
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
        
        # Valid signature, add funds to wallet
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        amount_inr = Decimal(str(amount_paise)) / Decimal('100')
        wallet.add_funds(amount_inr, description=f"Funds added via Razorpay (Order: {razorpay_order_id})")
        
        return JsonResponse({'success': True, 'message': f'Successfully added ₹{amount_inr} to your wallet!'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Payment verification failed.'})


@login_required
def my_bids(request):
    """Display user's bid history"""
    bids = Bid.objects.filter(user=request.user).select_related('lot', 'lot__auction').order_by('-timestamp')
    
    # Separate active and completed bids
    active_bids = bids.filter(lot__status='active')
    completed_bids = bids.filter(lot__status__in=['sold', 'unsold'])
    
    context = {
        'active_bids': active_bids,
        'completed_bids': completed_bids,
    }
    return render(request, 'bids/my_bids.html', context)


@login_required
def won_lots(request):
    """Display lots won by user"""
    won_lots = Lot.objects.filter(winning_bidder=request.user).select_related('auction').order_by('-updated_at')
    
    context = {
        'won_lots': won_lots,
    }
    return render(request, 'bids/won_lots.html', context)


@login_required
def place_bid_api(request, slug):
    """API endpoint to place a bid (fallback for non-WebSocket)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})
    
    try:
        lot = get_object_or_404(Lot, slug=slug)
        amount = Decimal(request.POST.get('amount', 0))
        
        # Get security deposit
        deposit = SecurityDeposit.objects.filter(user=request.user, status='active').exists()
        
        # Validate
        if lot.items.filter(owner=request.user).exists():
            return JsonResponse({'success': False, 'error': 'You cannot bid on your own lots/items.'})

        if lot.status != 'active':
            return JsonResponse({'success': False, 'error': 'Lot is not active'})

        # Block bids if a payment is pending for this lot
        if PendingPayment.objects.filter(lot=lot, status='pending').exists():
            return JsonResponse({'success': False, 'error': 'Auction closing: Payment is pending.'})

        # Prevent double bidding (consecutive bids by same user)
        if lot.winning_bidder == request.user:
            return JsonResponse({'success': False, 'error': 'You are already the highest bidder'})
        
        minimum_bid = lot.get_minimum_bid()
        if amount < minimum_bid:
            return JsonResponse({'success': False, 'error': f'Minimum bid is ₹{minimum_bid}'})
        
        if not deposit:
            return JsonResponse({'success': False, 'error': 'You must pay the ₹10,000 security deposit before placing a bid.'})
        
        # Create bid
        bid = Bid.objects.create(
            lot=lot,
            user=request.user,
            amount=amount
        )

        # --- BROADCAST TO WEBSOCKETS ---
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            room_group_name = f'lot_{lot.id}'
            
            bid_data = {
                'id': bid.id,
                'user': bid.user.username,
                'amount': float(bid.amount),
                'timestamp': bid.timestamp.isoformat(),
                'is_winning': True
            }
            
            # Broadcast bid update
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'bid_update', 
                    'bid': bid_data,
                    'minimum_bid': float(lot.get_minimum_bid()),
                    'bid_count': lot.bids.count()
                }
            )
            print(f"📡 Broadcasted bid {bid.id} to {room_group_name}")
            
        except Exception as e:
            print(f"⚠️ Broadcast missing: {e}")
        # -------------------------------
        
        return JsonResponse({
            'success': True,
            'bid': {
                'id': bid.id,
                'amount': float(bid.amount),
                'user': bid.user.username,
                'timestamp': bid.timestamp.isoformat(),
            },
            'current_bid': float(lot.current_bid),
            'minimum_bid': float(lot.get_minimum_bid()),
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def get_bid_updates(request, slug):
    """API endpoint for polling bid updates"""
    try:
        lot = Lot.objects.get(slug=slug)
        
        # Check for expired payments (Lazy check)
        from .utils import check_expired_payments
        check_expired_payments(lot)
        
        # Refresh lot to get potential new winner/status
        lot.refresh_from_db()

        
        # Auto-close logic
        time_remaining = lot.get_time_remaining()
        remaining_seconds = time_remaining.total_seconds() if time_remaining else 0
        
        # If time is up and lot is still active, close it
        if lot.status == 'active' and (lot.is_auction_ended() or (time_remaining is not None and remaining_seconds <= 0)):
            if lot.close_lot():
                lot.refresh_from_db()
                if lot.winning_bidder:
                    def send_winner_notification_sync(lot_id):
                        try:
                            from auction_list.models import Lot
                            from bids.invoice_generator import generate_invoice
                            from bids.email_utils import send_winner_email
                            lot_obj = Lot.objects.select_related('winning_bidder').get(id=lot_id)
                            path = generate_invoice(lot_obj, lot_obj.winning_bidder)
                            if path:
                                send_winner_email(lot_obj, lot_obj.winning_bidder, path)
                        except Exception as e:
                            print(f"Email Error: {e}")
                    send_winner_notification_sync(lot.id)
            
        # Serialize recent bids
        recent_bids = lot.recent_bids
        bids_data = []
        for bid in recent_bids:
            bids_data.append({
                'user': bid.user.username,
                'amount': float(bid.amount),
                'timestamp': bid.timestamp.isoformat(),
                'is_winning': bid.is_winning
            })
            
        # Serialize chats (optional, if we want to include chat in polling)
        # chats_data = ... 
        
        response_data = {
            'current_bid': float(lot.current_bid),
            'minimum_bid': float(lot.get_minimum_bid()),
            'time_remaining': remaining_seconds,
            'status': lot.status,
            'bids': bids_data,
            'bid_count': lot.bids.count(),
        }
        
        if lot.status == 'sold' and lot.winning_bidder:
            response_data['winner'] = lot.winning_bidder.username
            response_data['winning_bid'] = float(lot.current_bid)
            
        return JsonResponse(response_data)
        
    except Lot.DoesNotExist:
        return JsonResponse({'error': 'Lot not found'}, status=404)
    except Exception as e:
        print(f"Error in get_bid_updates: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def my_invoices(request):
    """List all invoices for the current user"""
    invoices = Invoice.objects.filter(user=request.user).select_related('lot', 'lot__auction').order_by('-issued_at')
    
    context = {
        'invoices': invoices
    }
    return render(request, 'bids/my_invoices.html', context)


@login_required
def invoice_detail(request, invoice_id):
    """Detailed view of a specific invoice"""
    # Import here or ensure top-level import (already added Invoice to top imports)
    invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)
    
    context = {
        'invoice': invoice,
        'lot': invoice.lot,
        'auction': invoice.lot.auction,
        'items': invoice.lot.items.all(),
        'user': request.user
    }
    return render(request, 'bids/invoice_detail.html', context)


from django.views.decorators.http import require_POST
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from datetime import timedelta
from .models import PendingPayment  # already imported at top, kept for clarity
from django.db import transaction as db_transaction


@login_required
@require_POST
def verify_payment_pin(request):
    """Verify Razorpay payment signature for won lot"""
    import json
    data = json.loads(request.body)
    lot_id = data.get('lot_id')
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    
    if not lot_id or not razorpay_payment_id:
        return JsonResponse({
            'success': False,
            'error': 'Missing required payment details'
        }, status=400)
    
    try:
        # Get lot and pending payment
        lot = get_object_or_404(Lot, id=lot_id)
        pending_payment = PendingPayment.objects.filter(
            lot=lot,
            user=request.user,
            status='pending'
        ).first()
        
        if not pending_payment:
            return JsonResponse({
                'success': False,
                'error': 'No pending payment found for this lot'
            }, status=404)
        
        if pending_payment.is_expired():
            return JsonResponse({
                'success': False,
                'error': 'Payment deadline has expired'
            }, status=400)
        
        # Verify Razorpay signature
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
             return JsonResponse({
                'success': False,
                'error': 'Invalid payment signature'
            }, status=400)
        
        # Process payment
        with db_transaction.atomic():
            # Mark payment as completed
            pending_payment.status = 'completed'
            pending_payment.pin_verified = True
            pending_payment.save()
            
            # Mark lot as paid (Awaiting Delivery)
            lot.status = 'paid'
            lot.save()
            
            # Create Secure Delivery Record
            from auction_list.models import Delivery
            delivery, created = Delivery.objects.get_or_create(lot=lot)
            delivery.generate_otp()
            delivery.status = 'pending'
            delivery.save()
            
            # Mark all items as sold
            items = lot.items.all()
            for item in items:
                item.status = 'Sold'
                item.save()
                
            winning_amount = Decimal(str(lot.current_bid))
            shipping_fee = Decimal(str(lot.shipping_fee))
            total_charge = pending_payment.amount_to_pay + shipping_fee
            
            # Generate invoice
            try:
                from auction_list.models import Invoice, send_invoice_email_task
                import uuid
                invoice = Invoice.objects.create(
                    user=request.user,
                    lot=lot,
                    amount=winning_amount,  # Actual bid amount
                    shipping_fee=shipping_fee,
                    invoice_number=f"INV-{lot.id}-{uuid.uuid4().hex[:8].upper()}",
                    status='paid'
                )
                
                # Send invoice email synchronously
                send_invoice_email_task(invoice.id)
            except Exception as e:
                print(f"Error creating invoice: {e}")
        
        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(lot)
        
        return JsonResponse({
            'success': True,
            'message': 'Payment completed successfully!',
            'lot_id': lot.id,
            'amount': float(pending_payment.amount_to_pay),
            'shipping_fee': float(shipping_fee),
            'total_amount': float(total_charge)
        })
        
    except Exception as e:
        print(f"Error in verify_payment_pin: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def payment_modal_fragment(request, slug):
    """
    GET: Creates a Razorpay Order and returns HTML to render the Razorpay Checkout flow instead of a Modal.
    """
    lot = get_object_or_404(Lot, slug=slug)
    
    if lot.winning_bidder != request.user:
        return JsonResponse({'html': ''})
        
    pending_payment = PendingPayment.objects.filter(
        lot=lot,
        user=request.user,
        status='pending'
    ).first()
    
    if not pending_payment:
        return JsonResponse({'html': ''})
        
    total_amount = pending_payment.amount_to_pay + lot.shipping_fee
    amount_in_paise = int(total_amount * 100)
    
    # Create razorpay order
    try:
        razorpay_order = razorpay_client.order.create({
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f'lot_{lot.id}_{pending_payment.id}'
        })
        
        context = {
            'lot': lot,
            'pending_payment': pending_payment,
            'total_amount': total_amount,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'amount_in_paise': amount_in_paise
        }
        
        return render(request, 'lots/partials/payment_modal.html', context)
    except Exception as e:
        return JsonResponse({'html': f'<div class="alert alert-danger">Error initializing payment gateway: {str(e)}</div>'})



@staff_member_required
def mark_at_warehouse(request, lot_id):
    """Admin confirms lot has arrived at the warehouse"""
    lot = get_object_or_404(Lot, id=lot_id)
    
    if lot.status != 'shipped_to_warehouse':
        messages.error(request, "Lot must be shipped to warehouse first.")
        return redirect('lot_detail', slug=lot.slug)
    
    try:
        delivery = lot.delivery
        delivery.status = 'at_warehouse'
        delivery.save()
        
        lot.status = 'at_warehouse'
        lot.save()
        
        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(lot)
        
        messages.success(request, f"Lot #{lot.lot_number} confirmed at warehouse.")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        
    return redirect('lot_detail', slug=lot.slug)


@staff_member_required
def mark_shipped_to_buyer(request, lot_id):
    """Admin marks lot as shipped from warehouse to buyer"""
    lot = get_object_or_404(Lot, id=lot_id)
    
    if lot.status != 'at_warehouse':
        messages.error(request, "Lot must be at warehouse before shipping to buyer.")
        return redirect('lot_detail', slug=lot.slug)
    
    try:
        delivery = lot.delivery
        delivery.status = 'shipped'
        delivery.save()
        
        lot.status = 'shipped'
        lot.save()
        
        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(lot)
        
        messages.success(request, f"Lot #{lot.lot_number} marked as shipped to buyer.")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        
    return redirect('lot_detail', slug=lot.slug)


@login_required
def confirm_delivery(request, lot_id):
    """View for buyer to confirm receipt of item"""
    lot = get_object_or_404(Lot, id=lot_id)
    
    if lot.winning_bidder != request.user:
        messages.error(request, "Only the buyer can confirm delivery.")
        return redirect('lot_detail', slug=lot.slug)
    
    if lot.status not in ['paid', 'shipped']:
        messages.error(request, "This lot is not in a deliverable state.")
        return redirect('lot_detail', slug=lot.slug)
    
    with db_transaction.atomic():
        try:
            from auction_list.models import Delivery
            delivery = lot.delivery
            delivery.status = 'delivered'
            delivery.delivered_at = timezone.now()
            delivery.save()
            
            lot.status = 'sold'
            lot.save()
            
            # Update all items in the lot to mark them as delivered
            for item in lot.items.all():
                item.pickup_status = 'delivered'
                item.save(update_fields=['pickup_status'])
            
            # Release funds to seller
            from .utils import release_seller_funds
            release_seller_funds(lot)
            
            from bids.utils import broadcast_lot_refresh
            broadcast_lot_refresh(lot)
            
            messages.success(request, f"Delivery confirmed for Lot #{lot.lot_number}. Funds released to seller.")
        except Exception as e:
            messages.error(request, f"Error confirming delivery: {str(e)}")
            
    return redirect('lot_detail', slug=lot.slug)


@login_required
@require_POST
def withdraw_funds(request):
    """Withdraw funds from user's wallet"""
    amount_str = request.POST.get('amount')
    pin = request.POST.get('pin')

    if not amount_str or not pin:
        return JsonResponse({'success': False, 'error': 'Amount and PIN are required.'}, status=400)

    try:
        amount = Decimal(amount_str)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid amount.'}, status=400)

    if amount < Decimal('500'):
        return JsonResponse({'success': False, 'error': 'Minimum withdrawal amount is ₹500.'}, status=400)

    # Verify transaction PIN
    try:
        profile = request.user.profile
        if not profile.transaction_pin:
            return JsonResponse({'success': False, 'error': 'Please set a transaction PIN first.'}, status=400)
        if not check_password(pin, profile.transaction_pin):
            return JsonResponse({'success': False, 'error': 'Incorrect transaction PIN.'}, status=400)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Error verifying PIN.'}, status=400)

    # Get wallet and check balance
    try:
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        if not wallet.has_sufficient_balance(amount):
            return JsonResponse({
                'success': False,
                'error': f'Insufficient balance. Available: ₹{wallet.balance:.0f}'
            }, status=400)

        # Deduct funds
        wallet.deduct_funds(amount, description=f"Withdrawal of ₹{amount:.0f}")

        return JsonResponse({
            'success': True,
            'message': f'Successfully withdrew ₹{amount:.0f} from your wallet.',
            'new_balance': float(wallet.balance)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def verify_delivery_otp(request):
    """View for seller to verify the OTP provided by the buyer"""
    lot_id = request.POST.get('lot_id')
    otp = request.POST.get('otp')
    
    lot = get_object_or_404(Lot, id=lot_id)
    
    # Check if user is Admin (Staff)
    # Seller cannot verify the code anymore, only the warehouse admin/courier can.
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized: Only Admin can verify delivery.'}, status=403)
        
    try:
        delivery = lot.delivery
        if delivery.verification_code == otp:
            with db_transaction.atomic():
                delivery.status = 'delivered'
                delivery.delivered_at = timezone.now()
                delivery.save()
                
                lot.status = 'sold'
                lot.save()
                
                # Update all items in the lot to mark them as delivered
                for item in lot.items.all():
                    item.pickup_status = 'delivered'
                    item.save(update_fields=['pickup_status'])
                
                # Release funds
                from .utils import release_seller_funds
                release_seller_funds(lot)
                
            return JsonResponse({'success': True, 'message': 'OTP verified successfully. Funds released.'})
        else:
            return JsonResponse({'success': False, 'error': 'Invalid OTP'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

