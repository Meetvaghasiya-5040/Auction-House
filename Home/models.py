from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    profile_image = models.ImageField(
        upload_to="profile_images/",
        blank=True,
        null=True,
        default="profile_images/default.png",
    )
    THEME_CHOICES = [
        ('indigo', 'Indigo (Default)'),
        ('emerald', 'Emerald'),
        ('rose', 'Rose'),
        ('amber', 'Amber'),
        ('cyan', 'Cyan'),
        ('slate', 'Slate'),
        ('violet', 'Violet'),
        ('fuchsia', 'Fuchsia'),
    ]
    theme_color = models.CharField(max_length=20, choices=THEME_CHOICES, default='indigo')
    bio = models.TextField(max_length=500, blank=True, help_text="Short bio about yourself")
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True, help_text="Shipping address")
    website = models.URLField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Profile"

    def get_profile_image_url(self):
        """Get profile image URL or default"""
        if self.profile_image and hasattr(self.profile_image, "url"):
            return self.profile_image.url
        return "/media/profile_images/default.png"

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"
