from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from .models import PendingPayment, Bid
from auction_list.models import Lot

def broadcast_lot_refresh(lot):
    """
    Broadcasts a WebSocket event to all clients watching this lot to dynamically
    reload the page. This keeps spectators' status badges and delivery forms 
    up-to-date instantly.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        room_group_name = f'lot_{lot.id}'
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'status_changed_refresh', 
                'data': {}
            }
        )
    except Exception as e:
        print(f"WebSocket Broadcast Error: {e}")

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

            # REFUND THE USER Logic (Removed for direct Razorpay flow)
            pass
            
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
                def send_new_winner_notification_sync(lot_id):
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
                        print(f"Email Error: {e}")
                send_new_winner_notification_sync(lot.id)
                broadcast_lot_refresh(lot)
                
            else:
                # 4. No more bidders - Mark Unsold
                lot.status = 'unsold'
                lot.winning_bidder = None
                lot.save(update_fields=['status', 'winning_bidder'])
                
                # Clear all winning flags
                Bid.objects.filter(lot=lot).update(is_winning=False)
                
                print("-> No more bidders. Marked as UNSOLD.")
                broadcast_lot_refresh(lot)

import threading

# Global lock to serialize proxy wars and prevent SQLite lock contention
PROXY_LOCK = threading.Lock()

def fire_proxy_bids(lot_id):
    """
    Core engine to handle automatic proxy bidding.
    Accepts lot_id instead of lot object to ensure fresh DB fetch in threads.
    """
    from django.db import transaction as db_tx
    from decimal import Decimal
    
    PROXY_LOCK.acquire()
    try:
        # Move imports inside to avoid circular dependency
        from .models import Bid, ProxyBid
        from auction_list.models import Lot
        
        iteration = 0
        
        while True:
            iteration += 1
            if iteration > 10: break

            with db_tx.atomic():
                # FRESH FETCH: Always get current state from DB with row lock
                try:
                    lot = Lot.objects.select_for_update().get(id=lot_id)
                except Lot.DoesNotExist:
                    print(f"[PROXY] Lot {lot_id} not found.")
                    break

                if lot.status != 'active': 
                    print(f"[PROXY] Lot {lot_id} is {lot.status}. Stopping.")
                    break

                current_price = lot.current_bid
                increment = lot.get_current_increment()
                current_winner_id = lot.winning_bidder_id

                print(f"[PROXY WAR] Lot {lot_id} | Round {iteration} | Current Bid: {current_price} | winner: {lot.winning_bidder}")

                # 1. Fetch all active proxies
                proxies = list(ProxyBid.objects.filter(
                    lot_id=lot_id, 
                    is_active=True
                ).order_by('-max_amount'))

                if not proxies:
                    print(f"[PROXY] No active proxies for Lot {lot_id}")
                    break

                # 2. Identify highest (P1) and competitor (P2)
                P1 = proxies[0]
                
                # If P1 is already the winner, they don't need to outbid themselves
                if P1.user_id == current_winner_id:
                    # Check if there's a competitor P2 to beat
                    competitor_proxies = [p for p in proxies if p.user_id != current_winner_id]
                    if not competitor_proxies:
                        print(f"[PROXY] {P1.user.username} is already winning with no competitors.")
                        break
                    
                    P2 = competitor_proxies[0]
                    # Target price: P2.max_amount + increment (capped by P1.max)
                    target_price = round(min(P1.max_amount, P2.max_amount + increment), 2)
                    
                    if current_price >= target_price:
                        print(f"[PROXY] {P1.user.username} already leading with sufficient price ₹{current_price}")
                        break
                    
                    new_price = target_price
                    winner_proxy = P1
                else:
                    # Current winner is NOT P1. We must outbid them.
                    competitors = [p for p in proxies if p.user_id != P1.user_id]
                    P2_max = competitors[0].max_amount if competitors else Decimal("0")
                    
                    # Target: Beat current winner AND any other proxies
                    new_price = round(min(P1.max_amount, max(current_price + increment, P2_max + increment)), 2)
                    
                    if new_price <= current_price:
                        print(f"[PROXY] Highest proxy {P1.user.username} (max ₹{P1.max_amount}) cannot outbid ₹{current_price}")
                        break
                        
                    winner_proxy = P1

                # 3. Create the Bid
                print(f"[PROXY WAR] --> PLACING BID: {winner_proxy.user.username} at ₹{new_price:.2f} (to beat ₹{current_price:.2f})")
                try:
                    auto_bid = Bid(
                        lot=lot,
                        user=winner_proxy.user,
                        amount=new_price,
                        is_auto_bid=True,
                    )
                    auto_bid.full_clean()
                    auto_bid.save()
                    print(f"[PROXY WAR] --> SUCCESS: Bid {auto_bid.id} saved.")
                    
                    # Ensure lot state is totally fresh for next loop
                    lot.refresh_from_db()
                except Exception as e:
                    print(f"[PROXY WAR] --> FAILED: {winner_proxy.user.username} bid error: {e}")
                    # Deactivate proxy if it fails validation (it's outbid)
                    winner_proxy.is_active = False
                    winner_proxy.save(update_fields=['is_active'])
                    
                    # Notify use via WS that they are outbid
                    try:
                        _notify_proxy_exceeded(winner_proxy, lot, lot.get_minimum_bid())
                    except: pass
                    break

        print(f"[PROXY WAR] War finished for Lot {lot_id} after {iteration} iterations.")

    except Exception as e:
        print(f"[PROXY] Critical FAILURE for Lot {lot_id}: {e}")
        import logging
        logging.getLogger(__name__).exception(e)
    finally:
        PROXY_LOCK.release()

def _notify_proxy_exceeded(proxy, lot, minimum_bid):
    """Helper to send WS notification when a proxy is outbid."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'user_{proxy.user.id}',
                {
                    'type': 'proxy_bid_exceeded',
                    'lot_id': lot.id,
                    'lot_title': lot.title,
                    'lot_slug': lot.slug,
                    'current_bid': float(lot.current_bid),
                    'minimum_bid': float(minimum_bid),
                    'your_max': float(proxy.max_amount),
                    'message': f'Your proxy bid limit of ₹{proxy.max_amount:,.0f} has been exceeded for "{lot.title}".'
                }
            )
    except Exception as e:
        print(f"[Proxy] WS notification error: {e}")


def broadcast_bid_update(lot):
    """Broadcast the current bid state to all WebSocket clients watching a lot."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        if channel_layer:
            # Calculate top-level fields
            time_rem = None
            try:
                rem = lot.get_time_remaining()
                if rem: time_rem = rem.total_seconds()
            except: pass

            async_to_sync(channel_layer.group_send)(
                f'lot_{lot.id}',
                {
                    'type': 'bid_update',
                    'bid': {
                        'user': lot.winning_bidder.username if lot.winning_bidder else '',
                        'amount': float(lot.current_bid),
                        'current_bid': float(lot.current_bid),
                        'minimum_bid': float(lot.get_minimum_bid()),
                        'timestamp': lot.last_bid_time.isoformat() if lot.last_bid_time else '',
                        'is_winning': True,
                    },
                    'minimum_bid': float(lot.get_minimum_bid()),
                    'bid_count': lot.bids.count(),
                    'time_remaining': time_rem
                }
            )
    except Exception as e:
        print(f"[Broadcast] bid_update error: {e}")


def release_seller_funds(lot):

    """
    Distribute funds to seller and admin after delivery is confirmed.
    Should be called within an atomic transaction.
    """
    from decimal import Decimal
    from bids.models import AdminWallet
    
    winning_amount = Decimal(str(lot.current_bid))
    shipping_fee = Decimal(str(lot.shipping_fee))
    items = lot.items.all()
    total_estimated_value = sum(item.estimated_value for item in items)
    
    # 1. Admin Commission
    # Real estate is 2%, normal items are 10%
    is_real_estate = False
    if hasattr(lot, 'lot_catagory') and lot.lot_catagory and getattr(lot.lot_catagory, 'is_immovable', False):
        is_real_estate = True
        
    admin_commission_pct = Decimal("0.02") if is_real_estate else Decimal("0.10")
    admin_commission = (winning_amount * admin_commission_pct).quantize(Decimal('0.01'))
    
    admin_wallet = AdminWallet.load()
    
    # Total to Admin = Commission only (shipping fee and buyer premium are credited elsewhere)
    total_to_admin = admin_commission
    
    item_type_label = "Real Estate" if is_real_estate else "Product"
    admin_wallet.add_funds(
        amount=total_to_admin,
        description=f"Commission ({admin_commission_pct*100}%) for Lot #{lot.lot_number} ({item_type_label})"
    )
    
    # 2. Distributable Amount (TO SELLER)
    # Seller gets: (Winning Bid - Admin Commission)
    distributable_amount = winning_amount - admin_commission
    
    lot_starting_price = Decimal(str(lot.starting_bid))
    # Fallback to sum of estimates to avoid division by zero
    if lot_starting_price <= 0:
        lot_starting_price = sum(Decimal(str(item.estimated_value)) for item in items)
        if lot_starting_price <= 0:
            lot_starting_price = Decimal("1")
    
    for item in items:
        item.status = 'Sold'
        item.save()
        
        # 3. Calculate User Share based on user formula: item-price / lot-price * (sold-price - commission)
        item_estimated_value = Decimal(str(item.estimated_value))
        if lot_starting_price > 0:
            share_percentage = item_estimated_value / lot_starting_price
            user_share = (share_percentage * distributable_amount).quantize(Decimal('0.01'))
            
            # Record Payout Requirement
            print(f"-> Seller payout required: ₹{user_share} for '{item.title}'")
            
            # Credit the UserWallet of the seller (item.owner)
            try:
                from bids.models import UserWallet
                wallet, _ = UserWallet.objects.get_or_create(user=item.owner)
                wallet.credit(
                    amount=user_share,
                    description=f"Payout for sold item '{item.title}' in Lot #{lot.lot_number}"
                )
                print(f"-> Credited ₹{user_share} to {item.owner.username}'s wallet")
            except Exception as e:
                print(f"-> Error crediting wallet for {item.owner.username}: {e}")

