import json
from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Item, Auction, Lot, Invoice, Delivery
from bids.models import PendingPayment

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

@receiver(post_save, sender=Item)
def item_status_changed(sender, instance, **kwargs):
    # Broadcast general status
    broadcast_status_change('item', instance.id, instance.status, instance.get_status_display())
    # Broadcast pickup status
    broadcast_status_change('item_pickup', instance.id, instance.pickup_status, instance.get_pickup_status_display())

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
