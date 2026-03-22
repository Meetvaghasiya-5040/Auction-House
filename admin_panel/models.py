from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class AdminNotification(models.Model):
    LEVEL_CHOICES = [
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]

    TYPE_CHOICES = [
        ('item_submitted', 'Item Submitted'),
        ('item_approved', 'Item Approved'),
        ('item_rejected', 'Item Rejected'),
        ('item_status', 'Item Status Changed'),
        ('general', 'General'),
    ]

    title        = models.CharField(max_length=200)
    message      = models.TextField()
    level        = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='general')

    # Related models (nullable)
    item         = models.ForeignKey('auction_list.Item', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='admin_notifications')
    triggered_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='triggered_notifications')

    is_read      = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_read', 'created_at']),
            models.Index(fields=['notification_type']),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.title} — {self.created_at.strftime('%d %b %H:%M')}"

    @property
    def is_archived(self):
        """Notifications older than 1 day are archived into history."""
        return self.created_at < timezone.now() - timedelta(hours=24)

    @property
    def level_icon(self):
        return {
            'info':    'fa-info-circle',
            'success': 'fa-check-circle',
            'warning': 'fa-exclamation-triangle',
            'error':   'fa-times-circle',
        }.get(self.level, 'fa-bell')

    @property
    def level_color_class(self):
        return {
            'info':    'text-blue-500 bg-blue-50',
            'success': 'text-emerald-600 bg-emerald-50',
            'warning': 'text-amber-600 bg-amber-50',
            'error':   'text-rose-600 bg-rose-50',
        }.get(self.level, 'text-slate-500 bg-slate-100')

    @classmethod
    def create_and_broadcast(cls, title, message, notification_type='general',
                              level='info', item=None, triggered_by=None, extra_data=None):
        """
        Create a notification record AND push it over WebSocket to the admin group.
        Call this from signals or views — it's safe to call from synchronous code.
        """
        notif = cls.objects.create(
            title=title,
            message=message,
            level=level,
            notification_type=notification_type,
            item=item,
            triggered_by=triggered_by,
        )
        
        payload = {
            'type': 'admin_notification',
            'notification_id': notif.id,
            'title': title,
            'message': message,
            'level': level,
            'notification_type': notification_type,
            'item_id': item.id if item else None,
            'item_slug': item.slug if item else None,
            'triggered_by': triggered_by.username if triggered_by else 'System',
            'timestamp': notif.created_at.strftime('%H:%M'),
        }
        
        if extra_data:
            payload['extra_data'] = extra_data
            
        # Broadcast to admin WS group
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    'admin_updates',
                    payload
                )
        except Exception:
            pass  # Never break user-facing requests over a WS failure
        return notif
