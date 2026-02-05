from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Auction, Lot


@receiver(post_save, sender=Auction)
def auction_status_broadcast(sender, instance, created, **kwargs):
    """Broadcast auction status on save"""
    # WebSocket broadcasting removed - only timezone fix kept
    pass


@receiver(post_save, sender=Lot)
def lot_status_broadcast(sender, instance, created, **kwargs):
    """Broadcast lot status on save"""
    # WebSocket broadcasting removed - only timezone fix kept
    pass

