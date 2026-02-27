import json
import asyncio
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Bid, Wallet
from auction_list.models import Lot
from django.db import transaction
from django.conf import settings

logger = logging.getLogger(__name__)

# Global tracker for active lot loops
active_lot_loops = {}

class BiddingConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time bidding & chat"""
    
    async def connect(self):
        """Handle WebSocket connection"""
        self.slug = self.scope['url_route']['kwargs'].get('slug')
        self.auction_id = self.scope['url_route']['kwargs'].get('auction_id')
        self.lot_id = None
        
        if self.slug:
            try:
                lot = await database_sync_to_async(Lot.objects.get)(slug=self.slug)
                self.lot_id = lot.id
                self.room_group_name = f'lot_{self.lot_id}'
            except Lot.DoesNotExist:
                await self.close()
                return
        elif self.auction_id:
            self.room_group_name = f'auction_{self.auction_id}'
        else:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Join user-specific group
        if self.scope['user'].is_authenticated:
            await self.channel_layer.group_add(
                f"user_{self.scope['user'].id}",
                self.channel_name
            )
        
        await self.accept()
        
        if self.lot_id:
            # Send initial sync data
            lot_data = await self.get_lot_data()
            await self.send(text_data=json.dumps({
                'type': 'lot_status',
                'data': lot_data
            }))

            # Start/Check tick loop
            task = active_lot_loops.get(self.lot_id)
            if not task or task.done():
                print(f"[WS] Starting new tick loop for Lot {self.lot_id}")
                active_lot_loops[self.lot_id] = asyncio.create_task(self.lot_tick_loop())
            else:
                # print(f"[WS] Loop already running for Lot {self.lot_id}")
                pass

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if self.scope['user'].is_authenticated:
            await self.channel_layer.group_discard(f"user_{self.scope['user'].id}", self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'place_bid':
                await self.handle_place_bid(data)
            elif message_type == 'send_chat':
                await self.handle_send_chat(data)
            elif message_type == 'request_status' and self.lot_id:
                lot_data = await self.get_lot_data()
                await self.send(text_data=json.dumps({'type': 'lot_status', 'data': lot_data}))
        except Exception as e:
            await self.send(text_data=json.dumps({'type': 'error', 'message': str(e)}))

    async def handle_place_bid(self, data):
        user = self.scope['user']
        if not user.is_authenticated or not self.lot_id: return
        
        bid_amount = data.get('amount')
        result = await self.place_bid(user.id, float(bid_amount))
        
        if result['success']:
            # Broadcast updated timer with the bid
            lot = await database_sync_to_async(Lot.objects.get)(id=self.lot_id)
            rem = await database_sync_to_async(lot.get_time_remaining)()
            time_rem = rem.total_seconds() if rem else None

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'bid_update', 
                    'bid': result['bid_data'],
                    'time_remaining': time_rem,
                    'minimum_bid': result['bid_data']['minimum_bid'],
                    'bid_count': await database_sync_to_async(lot.bids.count)()
                }
            )
            # Private wallet update
            await self.channel_layer.group_send(f"user_{user.id}", {'type': 'wallet_update', 'balance': result['wallet_balance']})
        else:
            await self.send(text_data=json.dumps({'type': 'error', 'message': result['error']}))

    async def handle_send_chat(self, data):
        user = self.scope['user']
        if not user.is_authenticated or not self.lot_id: return
        msg = data.get('message', '').strip()
        if not msg: return
        await self.save_chat_message(user, msg)
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat_message',
            'message': {'user': user.username, 'message': msg, 'timestamp': timezone.now().isoformat()}
        })

    @database_sync_to_async
    def save_chat_message(self, user, msg):
        from auction_list.models import LotChatMessage
        return LotChatMessage.objects.create(lot_id=self.lot_id, user=user, message=msg)

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'chat_message', 'message': event['message']}))

    async def bid_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'bid_update', 
            'bid': event['bid'],
            'minimum_bid': event.get('minimum_bid'),
            'bid_count': event.get('bid_count'),
            'time_remaining': event.get('time_remaining')
        }))

    async def wallet_update(self, event):
        await self.send(text_data=json.dumps({'type': 'wallet_update', 'balance': event['balance']}))

    async def timer_update(self, event):
        await self.send(text_data=json.dumps({'type': 'timer_update', 'data': event['data']}))

    async def auction_ended(self, event):
        await self.send(text_data=json.dumps({'type': 'auction_ended', 'data': event['data']}))

    async def lot_closed(self, event):
        await self.send(text_data=json.dumps({'type': 'lot_closed', 'data': event['data']}))

    async def lot_tick_loop(self):
        print(f"[Loop] Starting tick loop for Lot {self.lot_id}")
        try:
            while True:
                await asyncio.sleep(1)
                try:
                    from bids.models import PendingPayment
                    lot = await database_sync_to_async(Lot.objects.select_related('winning_bidder', 'auction').get)(id=self.lot_id)
                except Lot.DoesNotExist: break

                # 1. ALWAYS Broadcast Timer
                rem = await database_sync_to_async(lot.get_time_remaining)()
                time_rem = rem.total_seconds() if rem else 0
                
                await self.channel_layer.group_send(
                    self.room_group_name, 
                    {'type': 'timer_update', 'data': {'time_remaining': time_rem}}
                )

                # 2. Check Payments
                pending_payment = await database_sync_to_async(
                    lambda: PendingPayment.objects.filter(lot=lot, status='pending').first()
                )()
                if pending_payment:
                    if await database_sync_to_async(pending_payment.is_expired)():
                        await self.handle_payment_expiration(lot, pending_payment)
                    continue 
                
                # 3. End Check
                if lot.status == 'active' and lot.is_auction_ended():
                    await self.close_and_broadcast(lot)
                    continue

                if lot.status != 'active': break

                # 4. Countdown Overlay
                if 0 < time_rem <= 10:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {'type': 'timer_update', 'data': {'time_remaining': time_rem, 'countdown': time_rem}}
                    )

        except Exception as e:
            print(f"[Loop] Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            if self.lot_id in active_lot_loops: del active_lot_loops[self.lot_id]

    async def handle_payment_expiration(self, lot, pending_payment):
        await database_sync_to_async(self._process_expiration)(lot, pending_payment)
        updated = await database_sync_to_async(Lot.objects.select_related('winning_bidder').get)(id=self.lot_id)
        if updated.status == 'active' and updated.winning_bidder:
            await self.send_winner_notification(updated)
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'auction_ended',
                'data': {'winner': updated.winning_bidder.username, 'winning_bid': float(updated.current_bid), 'status': 'active'}
            })
        else:
            await self.channel_layer.group_send(self.room_group_name, {'type': 'lot_closed', 'data': {'status': 'unsold'}})

    def _process_expiration(self, lot, pending_payment):
        from bids.models import Bid, PendingPayment
        from datetime import timedelta
        with transaction.atomic():
            # Critical Race Condition Fix: Refresh and check status
            pending_payment.refresh_from_db()
            lot.refresh_from_db()
            
            sold_like_statuses = ['sold', 'paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped']
            if pending_payment.status != 'pending' or lot.status in sold_like_statuses:
                print(f"[Race Condition Avoided] Payment {pending_payment.id} is {pending_payment.status} or Lot is {lot.status}")
                return

            pending_payment.status = 'expired'; pending_payment.save()
            Bid.objects.filter(lot=lot, user=pending_payment.user, is_winning=True).update(is_winning=False)
            failed_users = PendingPayment.objects.filter(lot=lot, status__in=['expired', 'cancelled']).values_list('user', flat=True)
            next_bid = Bid.objects.filter(lot=lot).exclude(user__in=failed_users).order_by('-amount').first()
            if next_bid:
                lot.winning_bidder = next_bid.user; lot.current_bid = next_bid.amount; lot.save()
                next_bid.is_winning = True; next_bid.save()
                PendingPayment.objects.create(lot=lot, user=next_bid.user, amount=next_bid.amount, 
                     expires_at=timezone.now() + timedelta(minutes=settings.WINNER_PAYMENT_TIMEOUT_MINUTES), attempt_number=pending_payment.attempt_number + 1, status='pending')
            else:
                lot.status = 'unsold'; lot.winning_bidder = None; lot.save()

    async def close_and_broadcast(self, lot):
        success = await database_sync_to_async(lot.close_lot)()
        if success:
            lot = await database_sync_to_async(Lot.objects.select_related('winning_bidder').get)(id=self.lot_id)
            if lot.winning_bidder: await self.send_winner_notification(lot)
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'auction_ended',
                'data': {'winner': lot.winning_bidder.username if lot.winning_bidder else 'No Winner', 'winning_bid': float(lot.current_bid), 'status': lot.status}
            })

    async def send_winner_notification(self, lot):
        try:
            from .invoice_generator import generate_invoice
            from .email_utils import send_winner_email
            path = await database_sync_to_async(generate_invoice)(lot, lot.winning_bidder)
            if path: await database_sync_to_async(send_winner_email)(lot, lot.winning_bidder, path)
        except Exception as e: print(f"Email Error: {e}")

    @database_sync_to_async
    def place_bid(self, user_id, amount):
        from django.contrib.auth.models import User
        # Important: We need to get the lot within the transaction or just trust the ID is enough for the transaction content
        # But we need 'lot' object availability.
        lot = Lot.objects.get(id=self.lot_id) # Get fresh
        
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            # Re-fetch lot with lock? Or just check status
            if lot.status != 'active' or lot.is_auction_ended(): return {'success': False, 'error': 'Lot ended'}
            
            # Block bids if a payment is pending for this lot
            from bids.models import PendingPayment
            if PendingPayment.objects.filter(lot=lot, status='pending').exists():
                return {'success': False, 'error': 'Payment pending'}
            wallet, _ = Wallet.objects.get_or_create(user=user)
            min_bid = lot.get_minimum_bid()
            if Decimal(str(amount)) < min_bid: return {'success': False, 'error': f'Min ₹{min_bid}'}
            if not wallet.has_sufficient_balance(amount): return {'success': False, 'error': 'Insufficient funds'}
            Bid.objects.filter(lot=lot, is_winning=True).update(is_winning=False)
            bid = Bid.objects.create(lot=lot, user=user, amount=Decimal(str(amount)), is_winning=True)
            wallet.refresh_from_db()
            
            # Lot time extension logic should be HERE if it's not in the model save()
            # Assuming model handles it or we need to reload lot to get new end time if it changed
            lot.refresh_from_db() 
            
            return {'success': True, 'bid_data': {'user': user.username, 'amount': float(bid.amount), 'timestamp': bid.timestamp.isoformat(), 'minimum_bid': float(lot.get_minimum_bid())}, 'wallet_balance': float(wallet.balance)}

    @database_sync_to_async
    def get_lot_data(self):
        from auction_list.models import LotChatMessage
        try:
            lot = Lot.objects.select_related('winning_bidder').get(id=self.lot_id)
            bids = Bid.objects.filter(lot=lot).select_related('user').order_by('-timestamp')[:5]
            time_rem = lot.get_time_remaining().total_seconds() if lot.get_time_remaining() else None
            return {'current_bid': float(lot.current_bid), 'minimum_bid': float(lot.get_minimum_bid()), 'status': lot.status, 'time_remaining': time_rem, 'bid_count': lot.bids.count()}
        except: return {'error': 'Not found'}

class GlobalStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = 'global_status'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'data': event['data']
        }))

class AdminVerificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = 'admin_verification'
        
        # Accept the connection. The page itself is protected by staff_member_required view decorator.
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def new_item_pending(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_item_pending',
            'data': event['data']
        }))
