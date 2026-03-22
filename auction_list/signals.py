import json
from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Item, Auction, Lot, Invoice, Delivery
from bids.models import PendingPayment, SecurityDeposit


def broadcast_status_change(model_name, obj_id, new_status, status_display):
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            'global_status',
            {
                'type': 'status_update',
                'data': {
                    'model': model_name,
                    'id': str(obj_id),
                    'status': str(new_status),
                    'status_display': str(status_display)
                }
            }
        )


def notify_user_channel(user_id, payload):
    """Send a message to a specific user's personal WS channel."""
    channel_layer = get_channel_layer()
    if channel_layer:
        try:
            async_to_sync(channel_layer.group_send)(
                f'user_{user_id}',
                payload
            )
        except Exception:
            pass


@receiver(post_save, sender=Item)
def item_status_changed(sender, instance, created, **kwargs):
    # Always broadcast general status
    broadcast_status_change('item', instance.id, instance.status, instance.get_status_display())
    broadcast_status_change('item_pickup', instance.id, instance.pickup_status, instance.get_pickup_status_display())

    # NEW ITEM SUBMITTED
    if created and instance.status == 'Pending Approval':
        try:
            from admin_panel.models import AdminNotification
            AdminNotification.create_and_broadcast(
                title='New Item Submitted',
                message=f'"{instance.title}" submitted by {instance.owner.username} — awaiting verification.',
                notification_type='item_submitted',
                level='info',
                item=instance,
                triggered_by=instance.owner,
            )
        except Exception:
            pass

    # ITEM STATUS CHANGED BY ADMIN
    elif not created:
        # Notify user in real-time about their item's status change
        notify_user_channel(instance.owner_id, {
            'type': 'item_status_update',
            'item_id': instance.id,
            'item_title': instance.title,
            'status': instance.status,
            'status_display': instance.get_status_display(),
        })

        # Create admin notification for audit trail
        if instance.status in ('Approved', 'Rejected', 'Pickup Item', 'Warehouse'):
            try:
                from admin_panel.models import AdminNotification
                level = 'success' if instance.status == 'Approved' else (
                        'error' if instance.status == 'Rejected' else 'info')
                notif_type = {
                    'Approved': 'item_approved',
                    'Rejected': 'item_rejected',
                }.get(instance.status, 'item_status')
                AdminNotification.create_and_broadcast(
                    title=f'Item {instance.get_status_display()}',
                    message=f'"{instance.title}" (by {instance.owner.username}) -> {instance.get_status_display()}',
                    notification_type=notif_type,
                    level=level,
                    item=instance,
                )
            except Exception:
                pass


@receiver(post_save, sender=Auction)
def auction_status_changed(sender, instance, **kwargs):
    broadcast_status_change('auction', instance.id, instance.status, instance.get_status_display())

@receiver(post_save, sender=Lot)
def lot_status_changed(sender, instance, **kwargs):
    broadcast_status_change('lot', instance.id, instance.status, instance.get_status_display())

@receiver(post_save, sender=Invoice)
def invoice_status_changed(sender, instance, **kwargs):
    broadcast_status_change('invoice', instance.id, instance.status, instance.get_status_display())

@receiver(post_save, sender=Delivery)
def delivery_status_changed(sender, instance, **kwargs):
    broadcast_status_change('delivery', instance.id, instance.status, instance.get_status_display())

@receiver(post_save, sender=PendingPayment)
def payment_status_changed(sender, instance, **kwargs):
    broadcast_status_change('payment', instance.id, instance.status, instance.get_status_display())

@receiver(post_save, sender=SecurityDeposit)
def security_deposit_status_changed(sender, instance, created, **kwargs):
    # Broadcast to global status so admin pages can update in real-time
    broadcast_status_change('securitydeposit', instance.id, instance.status, instance.get_status_display())

    # If a deposit becomes active (or created as active)
    if instance.status == 'active':
        try:
            from admin_panel.models import AdminNotification
            username = instance.user.username if instance.user else "Unknown User"
            AdminNotification.create_and_broadcast(
                title='New Security Deposit',
                message=f'₹{instance.amount} security deposit paid by {username}.',
                notification_type='deposit_active',
                level='success',
                triggered_by=instance.user,
                # Pass additional structured info in the broadcast
                extra_data={
                    'deposit_id': instance.id,
                    'username': username,
                    'amount': str(instance.amount),
                    'gateway_id': instance.razorpay_payment_id or 'N/A',
                    'created_at': instance.created_at.strftime('%b. %d, %Y, %I:%M %p').replace('AM', 'a.m.').replace('PM', 'p.m.'),
                }
            )
        except Exception as e:
            print(f"Error broadcasting deposit: {e}")
