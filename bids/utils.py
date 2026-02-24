from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from .models import PendingPayment, Bid
from auction_list.models import Lot

def check_expired_payments(lot=None):
    """
    Check for expired pending payments and take action:
    1. Mark current payment as expired.
    2. Offer to next highest bidder.
    3. Or mark lot as unsold.
    
    If 'lot' is provided, checks only for that lot.
    """
    now = timezone.now()
    
    query = PendingPayment.objects.filter(
        status='pending',
        expires_at__lt=now
    )
    
    if lot:
        query = query.filter(lot=lot)
        
    expired_payments = query.all()
    
    for payment in expired_payments:
        with transaction.atomic():
            # Double check status inside transaction
            payment.refresh_from_db()
            lot = payment.lot
            
            # SAFETY CHECK: If lot is already sold/paid, or payment is not pending, do not expire!
            # Expanded status check to prevent 'paid' lots from being processed
            sold_like_statuses = ['sold', 'paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']
            if lot.status in sold_like_statuses or payment.status != 'pending':
                continue
                
            print(f"Processing expired payment for Lot {payment.lot.id} (User: {payment.user.username})")
            
            # 1. Mark as expired
            payment.status = 'expired'
            payment.save()

            # REFUND THE USER Logic
            try:
                from bids.models import Wallet
                wallet = Wallet.objects.get(user=payment.user)
                wallet.add_funds(
                    amount=payment.amount,
                    description=f"Refund: Payment expired for Lot #{lot.id}"
                )
                print(f"-> Refunded {payment.amount} to {payment.user.username}")
            except Exception as e:
                print(f"-> Error refunding user: {e}")
            
            # 2. Find Next Bidder
            # Get all bids for this lot, excluding the one from the expired user(s)
            # Actually, we should just look for the next highest bid from a *different* user 
            # who hasn't already expired/rejected.
            
            # Get list of users who have already failed
            failed_user_ids = PendingPayment.objects.filter(
                lot=lot, 
                status__in=['expired', 'cancelled']
            ).values_list('user_id', flat=True)
            
            # Find highest bid from a non-failed user
            next_bid = Bid.objects.filter(
                lot=lot
            ).exclude(
                user_id__in=failed_user_ids
            ).order_by('-amount').first()
            
            if next_bid:
                # 3. Create new Pending Payment for Next Bidder with centralized timeout
                new_expires_at = now + timedelta(minutes=settings.WINNER_PAYMENT_TIMEOUT_MINUTES)
                
                PendingPayment.objects.create(
                    lot=lot,
                    user=next_bid.user,
                    amount=next_bid.amount, # Offer at THEIR bid amount
                    expires_at=new_expires_at,
                    attempt_number=payment.attempt_number + 1,
                    status='pending'
                )
                
                # Update lot winner to this new user temporarily
                lot.winning_bidder = next_bid.user
                lot.current_bid = next_bid.amount # Update price to reflect the new winner's price? 
                # Usually standard auctions drop to the second highest bid price.
                lot.save(update_fields=['winning_bidder', 'current_bid'])
                
                # Update the specific bid to be winning?
                # We should probably reset all is_winning to False and set this one True
                Bid.objects.filter(lot=lot).update(is_winning=False)
                next_bid.is_winning = True
                next_bid.save()
                
                print(f"-> Offered to next bidder: {next_bid.user.username}")
                
                # Send email to the new winner
                import threading
                def send_new_winner_notification_bg(lot_id):
                    try:
                        from auction_list.models import Lot
                        from bids.invoice_generator import generate_invoice
                        from bids.email_utils import send_winner_email
                        lot_obj = Lot.objects.select_related('winning_bidder').get(id=lot_id)
                        if lot_obj.winning_bidder:
                            path = generate_invoice(lot_obj, lot_obj.winning_bidder)
                            if path:
                                send_winner_email(lot_obj, lot_obj.winning_bidder, path)
                    except Exception as e:
                        print(f"Background Email Error: {e}")
                threading.Thread(target=send_new_winner_notification_bg, args=(lot.id,)).start()
                
            else:
                # 4. No more bidders - Mark Unsold
                lot.status = 'unsold'
                lot.winning_bidder = None
                lot.save(update_fields=['status', 'winning_bidder'])
                
                # Clear all winning flags
                Bid.objects.filter(lot=lot).update(is_winning=False)
                
                print("-> No more bidders. Marked as UNSOLD.")


def release_seller_funds(lot):
    """
    Distribute funds to seller and admin after delivery is confirmed.
    Should be called within an atomic transaction.
    """
    from decimal import Decimal
    from bids.models import AdminWallet, Wallet
    
    winning_amount = Decimal(str(lot.current_bid))
    shipping_fee = Decimal(str(lot.shipping_fee))
    items = lot.items.all()
    total_estimated_value = sum(item.estimated_value for item in items)
    
    # 1. Admin Commission (10% of bid)
    admin_commission = winning_amount * Decimal("0.10")
    admin_wallet = AdminWallet.load()
    
    # Total to Admin = Commission + Buyer's Shipping Fee (Warehouse -> Buyer)
    total_to_admin = admin_commission + shipping_fee
    
    admin_wallet.add_funds(
        amount=total_to_admin,
        description=f"Commission + Shipping Fee for Lot #{lot.id}"
    )
    
    # 2. Distributable Amount (TO SELLER)
    # Seller gets: (Winning Bid - Admin Commission)
    # Seller already paid for shipping to Warehouse separately.
    distributable_amount = winning_amount - admin_commission
    
    for item in items:
        item.status = 'Sold'
        item.save()
        
        # 3. Calculate User Share
        if total_estimated_value > 0:
            share_percentage = Decimal(str(item.estimated_value)) / Decimal(str(total_estimated_value))
            user_share = share_percentage * distributable_amount
            
            # Credit Owner Wallet
            owner_wallet, created = Wallet.objects.get_or_create(user=item.owner)
            owner_wallet.add_funds(
                amount=user_share,
                description=f"Sale payout for '{item.title}' (Lot #{lot.id})"
            )
