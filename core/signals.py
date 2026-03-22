import json
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Registry of models we want to track globally
# Format: 'app_label.ModelName'
TRACKED_MODELS = [
    'bids.SecurityDeposit',
    'bids.Bid',
    'bids.Transaction',
    'auction_list.Lot',
    'auction_list.Item',
    'auction_list.Delivery',
    'Home.Profile',
]

def get_model_identifier(sender):
    """Returns 'app_label.ModelName'"""
    return f"{sender._meta.app_label}.{sender.__name__}"

def serialize_instance(instance):
    """Extremely basic serialization. For robust systems, DRF serializers are better."""
    data = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.name)
        # Handle some common non-serializable types safely
        if hasattr(value, 'isoformat'):  # datetime/date
            data[field.name] = value.isoformat()
        elif hasattr(value, '__str__') and not isinstance(value, str): # Decimal, UUID, etc
            data[field.name] = str(value)
        else:
            data[field.name] = value
            
        # Dynamically include human-readable display values for choice fields
        if getattr(field, 'choices', None):
            display_method = getattr(instance, f'get_{field.name}_display', None)
            if display_method:
                try:
                    data[f'{field.name}_display'] = display_method()
                except Exception:
                    pass
            
    # Include properties if needed (like get_status_display)
    if hasattr(instance, 'get_status_display'):
        try:
            data['status_display'] = instance.get_status_display()
        except Exception:
            pass
            
    return data

def broadcast_update(sender, instance, action):
    model_id = get_model_identifier(sender)
    
    if model_id not in TRACKED_MODELS:
        return
        
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
        
    packet = {
        'type': 'global_model_update',
        'data': {
            'action': action,
            'model': sender.__name__,
            'app_label': sender._meta.app_label,
            'pk': str(instance.pk),
            'fields': serialize_instance(instance) if action != 'delete' else {}
        }
    }
    
    # Broadcast to the global status channel
    print(f"====== BROADCASTING GLOBAL UPDATE: {packet} ======")
    async_to_sync(channel_layer.group_send)(
        'global_status',
        packet
    )
    print("====== BROADCAST SENT ======")

@receiver(post_save)
def global_post_save(sender, instance, created, **kwargs):
    action = 'create' if created else 'update'
    broadcast_update(sender, instance, action)

@receiver(post_delete)
def global_post_delete(sender, instance, **kwargs):
    broadcast_update(sender, instance, 'delete')
