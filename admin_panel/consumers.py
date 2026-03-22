import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class AdminConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for realtime admin dashboard updates.
    Handles item submission alerts, notification badge counts,
    metric updates, and general admin broadcasts.
    """

    async def connect(self):
        user = self.scope.get('user')
        if user and user.is_authenticated and user.is_staff:
            self.group_name = 'admin_updates'
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.channel_layer.group_add('global_status', self.channel_name)
            await self.accept()
            # Send current unread count on connect
            count = await self.get_unread_count()
            await self.send(text_data=json.dumps({
                'type': 'unread_count',
                'count': count,
            }))
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.channel_layer.group_discard('global_status', self.channel_name)

    async def receive(self, text_data):
        """Handle messages sent FROM the admin browser."""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'mark_read':
                notif_id = data.get('notification_id')
                if notif_id:
                    await self.mark_notification_read(notif_id)
                    count = await self.get_unread_count()
                    await self.send(text_data=json.dumps({
                        'type': 'unread_count',
                        'count': count,
                    }))

            elif action == 'mark_all_read':
                await self.mark_all_read()
                await self.send(text_data=json.dumps({
                    'type': 'unread_count',
                    'count': 0,
                }))
        except Exception:
            pass

    # ── Group message handlers ─────────────────────────────────────────

    async def admin_notification(self, event):
        """
        Handles a new notification broadcast from signals/views.
        Sends the notification popup + updated badge count.
        """
        count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'admin_notification',
            'notification_id': event.get('notification_id'),
            'title': event.get('title', ''),
            'message': event.get('message', ''),
            'level': event.get('level', 'info'),
            'notification_type': event.get('notification_type', 'general'),
            'item_id': event.get('item_id'),
            'item_slug': event.get('item_slug'),
            'triggered_by': event.get('triggered_by', ''),
            'timestamp': event.get('timestamp', ''),
            'unread_count': count,
        }))

    async def metric_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'metric_update',
            'data': event.get('data', {}),
        }))

    async def live_bid_update(self, event):
        """
        Handles real-time bid updates for the moderation panel.
        """
        await self.send(text_data=json.dumps({
            'type': 'live_bid_update',
            'bid': event.get('bid', {}),
        }))

    async def notification_update(self, event):
        """Re-sends the latest unread badge count."""
        count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': count,
        }))

    async def status_update(self, event):
        """Forward global status updates (lot/auction/item) to admin panel."""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'data': event.get('data', {}),
        }))

    async def global_model_update(self, event):
        """Handle model updates broadcasted directly via signals."""
        await self.send(text_data=json.dumps({
            'type': 'global_model_update',
            'data': event.get('data', {}),
        }))

    # ── Database helpers ───────────────────────────────────────────────

    @database_sync_to_async
    def get_unread_count(self):
        from admin_panel.models import AdminNotification
        return AdminNotification.objects.filter(is_read=False).count()

    @database_sync_to_async
    def mark_notification_read(self, notif_id):
        from admin_panel.models import AdminNotification
        AdminNotification.objects.filter(id=notif_id).update(is_read=True)

    @database_sync_to_async
    def mark_all_read(self):
        from admin_panel.models import AdminNotification
        AdminNotification.objects.filter(is_read=False).update(is_read=True)
