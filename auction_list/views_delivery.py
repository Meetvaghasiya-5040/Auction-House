from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from auction_list.models import Item, Lot, Delivery
from bids.models import Transaction, AdminWallet
from .utils import calculate_shipping_fee
from django.views.decorators.http import require_POST
from decimal import Decimal
from .email_notifications import (
    send_pickup_confirmed_email,
    send_item_at_warehouse_email,
    send_lot_ready_for_delivery_email,
    send_lot_shipped_email,
    send_lot_delivered_email
)

def is_admin(user):
    return user.is_staff

@login_required
@user_passes_test(is_admin)
def delivery_dashboard(request):
    """Admin dashboard for managing pickups and deliveries"""
    
    # Get separate search queries
    search_pickup = request.GET.get('search_pickup', '').strip()
    search_delivery = request.GET.get('search_delivery', '').strip()
    
    # 1. Pickup Requests (Items sold/lotted but not yet picked up)
    # Exclude immovable property items (real estate) — no physical pickup needed
    items_to_pickup = Item.objects.filter(
        pickup_status__in=['pending', 'picked_up']
    ).exclude(item_catagory__is_immovable=True)
    
    # Apply search filter for pickups
    if search_pickup:
        from django.db.models import Q
        items_to_pickup = items_to_pickup.filter(
            Q(title__icontains=search_pickup) |  # Search by item title
            Q(owner__username__icontains=search_pickup)  # Search by owner username
        )
    
    # 2. Delivery Requests (Lots paid but not delivered)
    # Filter lots that are 'paid', 'shipped_to_warehouse', 'at_warehouse'
    # EXCLUDE immovable property lots (they use PropertySale workflow)
    lots_to_deliver = Lot.objects.filter(
        status__in=['paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']
    ).exclude(
        lot_catagory__is_immovable=True
    ).select_related('delivery', 'winning_bidder')
    
    # Apply search filter for deliveries
    if search_delivery:
        from django.db.models import Q
        lots_to_deliver = lots_to_deliver.filter(
            Q(title__icontains=search_delivery) |  # Search by lot title
            Q(winning_bidder__username__icontains=search_delivery)  # Search by winner username
        )
    
    context = {
        'items_to_pickup': items_to_pickup,
        'lots_to_deliver': lots_to_deliver,
    }
    return render(request, 'auctions/delivery_dashboard.html', context)

@login_required
@user_passes_test(is_admin)
@require_POST
def verify_pickup_otp(request, item_id):
    """Verify OTP for Item Pickup from Seller"""
    item = get_object_or_404(Item, id=item_id)
    otp = request.POST.get('otp')
    courier_cost = request.POST.get('courier_cost')
    
    # Update Shipping Fee if provided
    if courier_cost:
        try:
            item.shipping_fee = Decimal(courier_cost)
            item.save(update_fields=['shipping_fee'])
        except Exception:
             messages.error(request, "Invalid Courier Cost")
             return redirect('delivery_dashboard')
    
    if item.pickup_otp == otp:
        # OTP Match!
        
        # Fund check removed (No Wallet system)
        pass

        try:
            with transaction.atomic():
                # 1. Update Status
                item.pickup_status = 'picked_up'
                item.save()
                
                # 2. Log Transaction (Optional, now linking to user)
                if item.shipping_fee > 0:
                    Transaction.objects.create(
                        user=item.owner,
                        transaction_type='deduction',
                        amount=item.shipping_fee,
                        description=f"Shipping Fee for Item: {item.title}"
                    )
                    
                    # Add to Admin Wallet
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(item.shipping_fee, description=f"Shipping Fee: {item.title}")

                # Send email notification to seller
                send_pickup_confirmed_email(item)
                    
            messages.success(request, f"Item '{item.title}' picked up successfully!")
            
        except Exception as e:
            messages.error(request, f"Error processing pickup: {e}")
            return redirect('delivery_dashboard')

    else:
        messages.error(request, "Invalid OTP. Please try again.")
        
    return redirect('delivery_dashboard')

@login_required
@user_passes_test(is_admin)
@require_POST
def verify_delivery_otp(request, lot_id):
    """Verify OTP for Lot Delivery to Buyer"""
    lot = get_object_or_404(Lot, id=lot_id)
    delivery = getattr(lot, 'delivery', None)
    otp = request.POST.get('otp')
    delivery_cost = request.POST.get('delivery_cost')
    
    if not delivery:
        messages.error(request, "Delivery record not found for this lot.")
        return redirect('delivery_dashboard')
    
    # Update Delivery Fee if provided
    if delivery_cost:
        try:
            lot.shipping_fee = Decimal(delivery_cost)
            lot.save(update_fields=['shipping_fee'])
        except Exception:
            messages.error(request, "Invalid Delivery Cost")
            return redirect('delivery_dashboard')
        
    if delivery.verification_code == otp:
        # OTP Match!
        
        # Fund check removed (No Wallet system)
        pass
        
        try:
            with transaction.atomic():
                # 1. Log Transaction
                if lot.shipping_fee > 0:
                    Transaction.objects.create(
                        user=lot.winning_bidder,
                        transaction_type='deduction',
                        amount=lot.shipping_fee,
                        description=f"Delivery Fee for Lot #{lot.lot_number}: {lot.title}"
                    )
                    
                    # Add to Admin Wallet
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(lot.shipping_fee, description=f"Delivery Fee: Lot #{lot.lot_number}")
                
                # 2. Update Delivery Status
                delivery.status = 'delivered'
                delivery.delivered_at = timezone.now()
                delivery.save()
                
                # 3. Update Lot Status
                lot.status = 'sold' # Final status
                lot.save()
                
                # 4. Update all items in the lot to mark them as delivered
                for item in lot.items.all():
                    item.pickup_status = 'delivered'
                    item.save(update_fields=['pickup_status'])
                
                # 5. Release funds to seller
                from bids.utils import release_seller_funds
                release_seller_funds(lot)
                
                # 6. Send delivery complete email to buyer and seller
                send_lot_delivered_email(lot)
                
            messages.success(request, f"Lot #{lot.lot_number} delivered successfully! Funds released to seller.")
            
        except Exception as e:
            messages.error(request, f"Error processing delivery: {e}")
            return redirect('delivery_dashboard')

    else:
        messages.error(request, "Invalid OTP. Please try again.")
        
    return redirect('delivery_dashboard')

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_mark_at_warehouse(request, item_id):
    """Mark item as arrived at warehouse"""
    print(f"🏭 Admin marking item {item_id} as at warehouse")
    item = get_object_or_404(Item, id=item_id)
    print(f"   Item found: {item.title}")
    item.pickup_status = 'at_warehouse'
    item.save()
    print(f"   Status updated to: {item.pickup_status}")
    
    # Send email notification to seller and buyer
    print(f"   Calling send_item_at_warehouse_email...")
    email_result = send_item_at_warehouse_email(item)
    print(f"   Email function returned: {email_result}")
    
    # Check if all items in the lot are at warehouse
    lot = item.lots.filter(status__in=['paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']).first()
    if lot:
        all_at_warehouse = all(
            item.pickup_status == 'at_warehouse' 
            for item in lot.items.all()
        )
        if all_at_warehouse:
            # Send lot ready for delivery email to buyer
            send_lot_ready_for_delivery_email(lot)
    
    messages.success(request, f"Item '{item.title}' marked as arrived at warehouse.")
    return redirect('delivery_dashboard')

@login_required
def user_delivery_tracking(request, lot_id):
    """User view to track delivery status of a won lot"""
    # Ensure user is the winner of the lot
    lot = get_object_or_404(Lot, id=lot_id, winning_bidder=request.user)
    
    # Redirect immovable property lots to PropertySale dashboard
    if lot.lot_catagory and getattr(lot.lot_catagory, 'is_immovable', False):
        return redirect('property_sale_dashboard', lot_id=lot.id)
    
    # Get delivery object if it exists
    delivery = getattr(lot, 'delivery', None)
    
    # Calculate progress for the UI
    status = delivery.status if delivery else lot.status
    if status == 'delivered':
        progress = 100
    elif status == 'shipped':
        progress = 75
    elif status in ['at_warehouse', 'shipped_to_warehouse']:
        progress = 50
    elif status in ['sold', 'draft', 'active']:
        progress = 0
    else:
        progress = 25
    
    context = {
        'lot': lot,
        'delivery': delivery,
        'item': lot.items.first(), # Assuming single item lots for now or primary item
        'progress': progress,
    }
    return render(request, 'auctions/delivery_tracking.html', context)

@login_required
@user_passes_test(is_admin)
def delivery_history(request):
    """Admin view for delivery history"""
    
    # Completed Pickups
    completed_pickups = Item.objects.exclude(
        pickup_status='pending'
    ).exclude(item_catagory__is_immovable=True).order_by('-id')
    
    # Completed Deliveries
    completed_deliveries = Lot.objects.filter(
        status='sold'
    ).select_related('delivery', 'winning_bidder').order_by('-id')
    
    context = {
        'completed_pickups': completed_pickups,
        'completed_deliveries': completed_deliveries,
    }
    return render(request, 'auctions/delivery_history.html', context)
