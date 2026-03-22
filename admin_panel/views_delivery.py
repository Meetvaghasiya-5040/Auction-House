from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from auction_list.models import Delivery, Invoice, Item, Lot
from django.utils import timezone
from decimal import Decimal
import json


@staff_member_required
def admin_delivery(request):
    """
    Comprehensive delivery dashboard bringing together:
    - Section 1: Pending Pickup jobs (Items with pickup_status=pending) — OTP form
    - Section 2: Picked-up items awaiting warehouse arrival  — 1-click button
    - Section 3: Lots ready for delivery to winner — Delivery OTP form
    - Section 4: Completed deliveries history tab
    """
    # --- SECTION 1 & 2: Item Pickup Pipeline ---
    # Exclude immovable property items (real estate) — no physical pickup needed
    items_pending_pickup = Item.objects.filter(
        pickup_status='pending'
    ).exclude(item_catagory__is_immovable=True).order_by('-id')

    items_picked_up = Item.objects.filter(
        pickup_status='picked_up'
    ).exclude(item_catagory__is_immovable=True).order_by('-id')

    # --- SECTION 3: Lot Delivery Pipeline ---
    # Exclude immovable property lots (they use PropertySale workflow)
    lots_to_deliver = Lot.objects.filter(
        status__in=['paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']
    ).exclude(lot_catagory__is_immovable=True).select_related('delivery', 'winning_bidder').order_by('-id')

    # --- SECTION 4: History ---
    completed_deliveries = Lot.objects.filter(
        status='sold'
    ).select_related('delivery', 'winning_bidder').order_by('-id')[:50]

    completed_pickups = Item.objects.filter(
        pickup_status='at_warehouse'
    ).order_by('-id')[:50]

    # --- Stat Counts ---
    stat = {
        'pending_pickup': items_pending_pickup.count(),
        'picked_up': items_picked_up.count(),
        'lots_to_deliver': lots_to_deliver.count(),
        'delivered': Lot.objects.filter(status='sold').count(),
    }

    context = {
        'items_pending_pickup': items_pending_pickup,
        'items_picked_up': items_picked_up,
        'lots_to_deliver': lots_to_deliver,
        'completed_deliveries': completed_deliveries,
        'completed_pickups': completed_pickups,
        'stat': stat,
    }
    return render(request, 'admin_panel/delivery.html', context)


@staff_member_required
@require_POST
def admin_verify_pickup_otp(request, item_id):
    """Verify seller OTP and mark item as Picked Up."""
    item = get_object_or_404(Item, id=item_id)
    otp = request.POST.get('otp', '').strip()
    courier_cost = request.POST.get('courier_cost', '').strip()

    if courier_cost:
        try:
            item.shipping_fee = Decimal(courier_cost)
            item.save(update_fields=['shipping_fee'])
        except Exception:
            messages.error(request, "Invalid Courier Cost. Please enter a valid number.")
            return redirect('admin_panel:delivery')

    if item.pickup_otp == otp:
        try:
            with transaction.atomic():
                item.pickup_status = 'picked_up'
                item.status = 'Pickup Item'
                item.save()

                # Log transaction to seller wallet
                from bids.models import Transaction, AdminWallet
                if item.shipping_fee and item.shipping_fee > 0:
                    Transaction.objects.create(
                        user=item.owner,
                        transaction_type='deduction',
                        amount=item.shipping_fee,
                        description=f"Shipping Fee for Item: {item.title}"
                    )
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(item.shipping_fee, description=f"Shipping Fee: {item.title}")

                # Send confirmation email to seller
                from auction_list.email_notifications import send_pickup_confirmed_email
                send_pickup_confirmed_email(item)

            messages.success(request, f"✅ Item '{item.title}' picked up successfully!")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    else:
        messages.error(request, "❌ Invalid OTP. Please ask the seller to share the correct OTP.")

    return redirect('admin_panel:delivery')


@staff_member_required
@require_POST
def admin_mark_at_warehouse(request, item_id):
    """Mark a picked-up item as arrived at warehouse — no OTP needed."""
    item = get_object_or_404(Item, id=item_id)
    item.pickup_status = 'at_warehouse'
    item.status = 'Warehouse'
    item.save()

    # Check if all items in the lot are now at warehouse → notify buyer
    from auction_list.email_notifications import send_item_at_warehouse_email, send_lot_ready_for_delivery_email
    send_item_at_warehouse_email(item)

    lot = item.lots.filter(status__in=['paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']).first()
    if lot:
        all_at_warehouse = all(i.pickup_status == 'at_warehouse' for i in lot.items.all())
        if all_at_warehouse:
            send_lot_ready_for_delivery_email(lot)

    messages.success(request, f"🏭 Item '{item.title}' marked as arrived at warehouse!")
    return redirect('admin_panel:delivery')


@staff_member_required
@require_POST
def admin_verify_delivery_otp(request, lot_id):
    """Verify buyer OTP and mark lot as Delivered."""
    lot = get_object_or_404(Lot, id=lot_id)
    delivery = getattr(lot, 'delivery', None)
    otp = request.POST.get('otp', '').strip()
    delivery_cost = request.POST.get('delivery_cost', '').strip()

    if not delivery:
        messages.error(request, "No delivery record found for this lot.")
        return redirect('admin_panel:delivery')

    if delivery_cost:
        try:
            lot.shipping_fee = Decimal(delivery_cost)
            lot.save(update_fields=['shipping_fee'])
        except Exception:
            messages.error(request, "Invalid Delivery Cost.")
            return redirect('admin_panel:delivery')

    if delivery.verification_code == otp:
        try:
            with transaction.atomic():
                # Log delivery fee transaction
                from bids.models import Transaction, AdminWallet
                if lot.shipping_fee and lot.shipping_fee > 0:
                    Transaction.objects.create(
                        user=lot.winning_bidder,
                        transaction_type='deduction',
                        amount=lot.shipping_fee,
                        description=f"Delivery Fee for Lot #{lot.lot_number}: {lot.title}"
                    )
                    admin_wallet = AdminWallet.load()
                    admin_wallet.add_funds(lot.shipping_fee, description=f"Delivery Fee: Lot #{lot.lot_number}")

                # Mark delivery as delivered
                delivery.status = 'delivered'
                delivery.delivered_at = timezone.now()
                delivery.save()

                # Mark lot as sold
                lot.status = 'sold'
                lot.save()

                # Mark all items in lot as delivered
                for item in lot.items.all():
                    item.pickup_status = 'delivered'
                    item.save(update_fields=['pickup_status'])

                # Release funds to seller
                from bids.utils import release_seller_funds
                release_seller_funds(lot)

                # Send email to buyer and seller
                from auction_list.email_notifications import send_lot_delivered_email
                send_lot_delivered_email(lot)

            messages.success(request, f"🎉 Lot #{lot.lot_number} delivered! Funds released to seller.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    else:
        messages.error(request, "❌ Invalid OTP. Please ask the buyer to share the correct delivery OTP.")

    return redirect('admin_panel:delivery')


@staff_member_required
def admin_invoices(request):
    """Dedicated Invoice management page."""
    invoices = Invoice.objects.all().select_related('lot', 'user').order_by('-issued_at')
    total_paid = sum(inv.amount for inv in invoices if inv.status == 'paid')
    paid_count = invoices.filter(status='paid').count()
    pending_count = invoices.filter(status='pending').count()
    context = {
        'invoices': invoices,
        'total_paid': total_paid,
        'paid_count': paid_count,
        'pending_count': pending_count,
    }
    return render(request, 'admin_panel/invoices.html', context)


@staff_member_required
def update_delivery_status(request, delivery_id):
    """AJAX endpoint to update delivery status and tracking number."""
    if request.method == 'POST':
        delivery = get_object_or_404(Delivery, id=delivery_id)
        data = json.loads(request.body)

        new_status = data.get('status')
        tracking_number = data.get('tracking_number')

        valid_statuses = ['pending', 'shipped_to_warehouse', 'at_warehouse', 'shipped', 'delivered', 'disputed']

        if new_status and new_status in valid_statuses:
            delivery.status = new_status
            if new_status == 'shipped' and not delivery.shipped_at:
                delivery.shipped_at = timezone.now()
                from auction_list.email_notifications import send_lot_shipped_email
                send_lot_shipped_email(delivery.lot, delivery)
            elif new_status == 'delivered' and not delivery.delivered_at:
                delivery.delivered_at = timezone.now()
                from auction_list.email_notifications import send_lot_delivered_email
                send_lot_delivered_email(delivery.lot)

        if tracking_number is not None:
            delivery.tracking_number = tracking_number

        delivery.save()

        from bids.utils import broadcast_lot_refresh
        broadcast_lot_refresh(delivery.lot)

        return JsonResponse({'success': True, 'status': delivery.status, 'tracking_number': delivery.tracking_number})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
