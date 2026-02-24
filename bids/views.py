from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from decimal import Decimal
from .models import Wallet, Bid, Transaction
from auction_list.models import Lot, Invoice


@login_required
def wallet_dashboard(request):
    """Display user's wallet dashboard"""
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-timestamp')[:50]
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    return render(request, 'bids/wallet_dashboard.html', context)


@login_required
def add_funds(request):
    """Add funds to user's wallet"""
    if request.method == 'POST':
        amount = request.POST.get('amount')
        pin = request.POST.get('pin')
        
        # Verify PIN
        try:
            if not hasattr(request.user, 'profile') or not request.user.profile.transaction_pin:
                messages.error(request, 'Please set a transaction PIN first')
                return redirect('profile')
            
            if not check_password(pin, request.user.profile.transaction_pin):
                messages.error(request, 'Incorrect Transaction PIN')
                return redirect('profile')
        except Exception as e:
            messages.error(request, 'Error verifying PIN')
            return redirect('profile')
        
        try:
            amount = Decimal(amount)
            if amount <= 0:
                messages.error(request, 'Amount must be positive')
                return redirect('profile')
            
            wallet, created = Wallet.objects.get_or_create(user=request.user)
            wallet.add_funds(amount, description=f"Funds added via wallet dashboard")
            
            messages.success(request, f'Successfully added ₹{amount} to your wallet')
            return redirect('profile')
            
        except (ValueError, TypeError):
            messages.error(request, 'Invalid amount')
            return redirect('profile')
    
    return render(request, 'bids/add_funds.html')


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
        
        # Get or create wallet
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        
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
        
        if not wallet.has_sufficient_balance(amount):
            return JsonResponse({'success': False, 'error': f'Insufficient balance. Your balance: ₹{wallet.balance}'})
        
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
            'wallet_balance': float(request.user.wallet.balance),
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
            lot.close_lot()
            lot.refresh_from_db()
            
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
from .models import PendingPayment
from django.db import transaction as db_transaction


@login_required
@require_POST
def verify_payment_pin(request):
    """Verify PIN and complete payment for won lot"""
    lot_id = request.POST.get('lot_id')
    pin = request.POST.get('pin')
    
    if not lot_id or not pin:
        return JsonResponse({
            'success': False,
            'error': 'Lot ID and PIN are required'
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
        
        # Check if payment has expired
        if pending_payment.is_expired():
            return JsonResponse({
                'success': False,
                'error': 'Payment deadline has expired'
            }, status=400)
        
        # Verify PIN
        try:
            profile = request.user.profile
        except:
            return JsonResponse({
                'success': False,
                'error': 'Profile not found'
            }, status=400)
        
        if not check_password(pin, profile.transaction_pin):
            return JsonResponse({
                'success': False,
                'error': 'Incorrect PIN'
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
            
            # Mark all items as sold (but payout happens later)
            items = lot.items.all()
            for item in items:
                item.status = 'Sold'
                item.save()
                
            winning_amount = Decimal(str(lot.current_bid))
            shipping_fee = Decimal(str(lot.shipping_fee))
            total_charge = winning_amount + shipping_fee
            
            # Generate invoice
            try:
                from auction_list.models import Invoice, send_invoice_email_task
                import uuid
                import threading
                
                invoice = Invoice.objects.create(
                    user=request.user,
                    lot=lot,
                    amount=winning_amount,
                    shipping_fee=shipping_fee,
                    invoice_number=f"INV-{lot.id}-{uuid.uuid4().hex[:8].upper()}",
                    status='paid'
                )
                
                # Send invoice email in background
                threading.Thread(target=send_invoice_email_task, args=(invoice.id,)).start()
            except Exception as e:
                print(f"Error creating invoice: {e}")
        
        return JsonResponse({
            'success': True,
            'message': 'Payment completed successfully!',
            'lot_id': lot.id,
            'amount': float(winning_amount),
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
    GET: Returns the HTML fragment for the payment PIN modal.
    POST: Verifies PIN and completes payment for won auction.
    """
    lot = get_object_or_404(Lot, slug=slug)
    
    # Handle POST request - PIN verification
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            pin = data.get('pin', '').strip()
            
            # Verify user is the winner
            if lot.winning_bidder != request.user:
                return JsonResponse({
                    'success': False,
                    'message': 'You are not the winner of this auction'
                })
            
            # Verify PIN
            wallet = request.user.wallet
            if not wallet.verify_transaction_pin(pin):
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid PIN. Please try again.'
                })
            
            # PIN is correct - payment already deducted when bid was placed
            # Just mark the lot as sold
            lot.status = 'sold'
            lot.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Payment confirmed successfully!'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'An error occurred: {str(e)}'
            })
    
    # Handle GET request - return HTML fragment
    # Show modal if user is the winning bidder and has a pending payment
    # (Status might still be 'active' while awaiting payment)
    if lot.winning_bidder != request.user:
        return JsonResponse({'html': ''}) # Return empty if not the winner
        
    pending_payment = PendingPayment.objects.filter(
        lot=lot,
        user=request.user,
        status='pending'
    ).first()
    
    # If no pending payment exists, don't show modal
    if not pending_payment:
        return JsonResponse({'html': ''})
    
    context = {
        'lot': lot,
        'pending_payment': pending_payment,
    }
    
    # Render just the partial
    return render(request, 'lots/partials/payment_modal.html', context)


@login_required
def mark_shipped_to_warehouse(request, lot_id):
    """View for seller to mark a lot as shipped to the warehouse"""
    lot = get_object_or_404(Lot, id=lot_id)
    
    # Check if user is the owner of any item in this lot
    if not lot.items.filter(owner=request.user).exists():
        messages.error(request, "You are not authorized to mark this lot as shipped.")
        return redirect('lot_detail', slug=lot.slug)
    
    if lot.status != 'paid':
        messages.error(request, "Lot must be paid before shipping to warehouse.")
        return redirect('lot_detail', slug=lot.slug)
    
    try:
        from auction_list.models import Delivery
        delivery = lot.delivery
        delivery.status = 'shipped_to_warehouse'
        delivery.shipped_at = timezone.now()
        
        if request.method == 'POST':
            delivery.tracking_number = request.POST.get('tracking_number')
        
        delivery.save()
        
        lot.status = 'shipped_to_warehouse'
        lot.save()
        
        messages.success(request, f"Lot #{lot.lot_number} marked as shipped to warehouse.")
    except Exception as e:
        messages.error(request, f"Error updating delivery: {str(e)}")
        
    return redirect('lot_detail', slug=lot.slug)


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

