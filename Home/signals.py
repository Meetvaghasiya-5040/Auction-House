from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    """Create a Profile when a new User is created."""
    if created:
        # Only create if one doesn't already exist
        # (register_view may have already created it with an image)
        Profile.objects.get_or_create(user=instance)

# NOTE: The save_profile signal that called instance.profile.save() on every
# User.save() has been intentionally removed. It was overwriting the profile
# image set during registration because login() triggers User.save() internally.
