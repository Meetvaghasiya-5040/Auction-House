import json
import asyncio
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from decimal import Decimal
from .models import Bid, Wallet
from auction_list.models import Lot

logger = logging.getLogger(__name__)

# Global tracker for active lot loops
active_lot_loops = {}

class BiddingConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time bidding & chat"""
    
    async def connect(self):
        """Handle WebSocket connection"""
        self.lot_id = self.scope['url_route']['kwargs'].get('lot_id')
        self.auction_id = self.scope['url_route']['kwargs'].get('auction_id')
        
        if self.lot_id:
            self.room_group_name = f'lot_{self.lot_id}'
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
        
        # Join user-specific group for private updates (like wallet)
        if self.scope['user'].is_authenticated:
            await self.channel_layer.group_add(
                f"user_{self.scope['user'].id}",
                self.channel_name
            )
        
        await self.accept()
        
        # Only start loops and send initial data if it's a LOT connection
        if self.lot_id:
            lot_data = await self.get_lot_data()
            await self.send(text_data=json.dumps({
                'type': 'lot_status',
                'data': lot_data
            }))

            if self.lot_id not in active_lot_loops:
                active_lot_loops[self.lot_id] = asyncio.create_task(self.lot_tick_loop())
        elif self.auction_id:
            # For auction-level connections, maybe send current auction status
            await self.send(text_data=json.dumps({
                'type': 'info',
                'message': f'Connected to Auction #{self.auction_id}'
            }))
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        if self.scope['user'].is_authenticated:
            await self.channel_layer.group_discard(
                f"user_{self.scope['user'].id}",
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Receive message from WebSocket"""
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
        """Handle bid placement"""
        user = self.scope['user']
        if not user.is_authenticated or not self.lot_id:
            return
        
        bid_amount = data.get('amount')
        result = await self.place_bid(user.id, float(bid_amount))
        
        if result['success']:
            # 1. Update Bidder's wallet
            await self.channel_layer.group_send(
                f"user_{user.id}",
                {'type': 'wallet_update', 'balance': result['wallet_balance']}
            )
            # 2. Update Previous Winner's wallet
            if result.get('prev_winner_id'):
                 await self.channel_layer.group_send(
                    f"user_{result['prev_winner_id']}",
                    {'type': 'wallet_update', 'balance': result['prev_winner_balance']}
                )
            # 3. Broadcast bid
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'bid_update', 'bid': result['bid_data']}
            )
        else:
            await self.send(text_data=json.dumps({'type': 'error', 'message': result['error']}))

    async def handle_send_chat(self, data):
        """Handle chat message"""
        user = self.scope['user']
        if not user.is_authenticated or not self.lot_id:
            return
        
        message_text = data.get('message', '').strip()
        if not message_text: return
            
        await self.save_chat_message(user, message_text)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': {
                    'user': user.username,
                    'message': message_text,
                    'timestamp': timezone.now().isoformat()
                }
            }
        )

    @database_sync_to_async
    def save_chat_message(self, user, message_text):
        from auction_list.models import LotChatMessage
        lot = Lot.objects.get(id=self.lot_id)
        return LotChatMessage.objects.create(lot=lot, user=user, message=message_text)

    # Broadcast handlers
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'chat_message', 'message': event['message']}))
    
    async def bid_update(self, event):
        await self.send(text_data=json.dumps({'type': 'bid_update', 'bid': event['bid']}))

    async def wallet_update(self, event):
        await self.send(text_data=json.dumps({'type': 'wallet_update', 'balance': event['balance']}))
    
    async def timer_update(self, event):
        await self.send(text_data=json.dumps({'type': 'timer_update', 'data': event['data']}))
    
    async def auction_ended(self, event):
        await self.send(text_data=json.dumps({'type': 'auction_ended', 'data': event['data']}))

    async def lot_tick_loop(self):
        """Infinite background loop for lot lifecycle management"""
        print(f"[Loop] Starting tick loop for Lot {self.lot_id}")
        try:
            while True:
                await asyncio.sleep(1)
                try:
                    lot = await database_sync_to_async(Lot.objects.select_related('winning_bidder').get)(id=self.lot_id)
                except Lot.DoesNotExist: break
                
                if lot.status != 'active':
                    print(f"[Loop] Lot {self.lot_id} is no longer active ({lot.status}). Stopping.")
                    break
                
                # Timed Auction End Check
                if lot.is_timed and lot.is_auction_ended():
                    print(f"[Loop] Lot {self.lot_id} timed auction ended.")
                    await self.close_and_broadcast(lot)
                    break

                # Time Remaining Broadcast for timed auctions
                if lot.is_timed:
                    rem = lot.get_time_remaining()
                    if rem:
                        time_remaining_seconds = rem.total_seconds()
                        
                        # Broadcast regular timer update
                        await self.channel_layer.group_send(
                            self.room_group_name, 
                            {
                                'type': 'timer_update', 
                                'data': {'time_remaining': time_remaining_seconds}
                            }
                        )
                        
                        # Broadcast countdown when within 10 seconds
                        if time_remaining_seconds <= 10 and time_remaining_seconds > 0:
                            await self.channel_layer.group_send(
                                self.room_group_name,
                                {
                                    'type': 'timer_update',
                                    'data': {
                                        'time_remaining': time_remaining_seconds,
                                        'countdown': time_remaining_seconds
                                    }
                                }
                            )

        except Exception as e:
            print(f"[Loop] CRITICAL ERROR for Lot {self.lot_id}: {e}")
        finally:
            if self.lot_id in active_lot_loops:
                del active_lot_loops[self.lot_id]

    async def close_and_broadcast(self, lot):
        """Safely close lot and notify users"""
        try:
            success = await database_sync_to_async(lot.close_lot)()
            if success:
                # Refresh to get winner details
                lot = await database_sync_to_async(Lot.objects.select_related('winning_bidder').get)(id=self.lot_id)
                print(f"[Loop] Lot {self.lot_id} closed. Status: {lot.status}, Winner: {lot.winning_bidder}")
                
                # Generate invoice and send email if there's a winner
                if lot.winning_bidder:
                    await self.send_winner_notification(lot)
                    print(f"[Loop] Lot SOLD to {lot.winning_bidder.username} for ₹{lot.current_bid}")
                else:
                    print(f"[Loop] Lot closed with NO bids - marked as {lot.status}")
                
                # ALWAYS broadcast auction_ended (whether winner exists or not)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'auction_ended',
                        'data': {
                            'winner': lot.winning_bidder.username if lot.winning_bidder else 'No Winner',
                            'winning_bid': float(lot.current_bid),
                            'status': lot.status  # Include status for debugging
                        }
                    }
                )
                print(f"[Loop] Broadcasted auction_ended message to all clients")
        except Exception as e:
            print(f"[Loop] Error closing lot {self.lot_id}: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_winner_notification(self, lot):
        """Generate invoice and send winner email"""
        try:
            from .invoice_generator import generate_invoice
            from .email_utils import send_winner_email
            
            # Generate invoice
            invoice_path = await database_sync_to_async(generate_invoice)(lot, lot.winning_bidder)
            
            # Send email with invoice
            if invoice_path:
                await database_sync_to_async(send_winner_email)(lot, lot.winning_bidder, invoice_path)
                print(f"[Email] Winner notification sent to {lot.winning_bidder.email}")
            else:
                print(f"[Email] Failed to generate invoice for lot {self.lot_id}")
        except Exception as e:
            print(f"[Email] Error sending winner notification: {e}")

    @database_sync_to_async
    def place_bid(self, user_id, bid_amount):
        from django.contrib.auth.models import User
        from django.db import transaction
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(id=user_id)
                lot = Lot.objects.select_for_update().get(id=self.lot_id)
                if lot.status != 'active' or lot.is_auction_ended():
                     return {'success': False, 'error': 'Lot is not active or has ended'}
                
                wallet, _ = Wallet.objects.get_or_create(user=user)
                min_bid = lot.get_minimum_bid()
                if Decimal(str(bid_amount)) < min_bid:
                    return {'success': False, 'error': f'Min bid ₹{min_bid}'}
                if not wallet.has_sufficient_balance(bid_amount):
                    return {'success': False, 'error': 'Insufficient balance'}
                
                prev_winner = Bid.objects.filter(lot=lot, is_winning=True).first()
                bid = Bid.objects.create(lot=lot, user=user, amount=Decimal(str(bid_amount)))
                
                wallet.refresh_from_db()
                prev_winner_bal = None
                if prev_winner:
                    pw_wallet = Wallet.objects.get(user=prev_winner.user)
                    prev_winner_bal = float(pw_wallet.balance)

                return {
                    'success': True, 
                    'bid_data': {
                        'id': bid.id, 'user': user.username, 'amount': float(bid.amount),
                        'timestamp': bid.timestamp.isoformat(), 'current_bid': float(lot.current_bid),
                        'minimum_bid': float(lot.get_minimum_bid()), 'is_winning': bid.is_winning
                    }, 
                    'wallet_balance': float(wallet.balance),
                    'prev_winner_id': prev_winner.user.id if prev_winner else None,
                    'prev_winner_balance': prev_winner_bal
                }
        except Exception as e: return {'success': False, 'error': str(e)}

    @database_sync_to_async
    def get_lot_data(self):
        from auction_list.models import LotChatMessage
        try:
            lot = Lot.objects.select_related('winning_bidder').get(id=self.lot_id)
            recent_bids = Bid.objects.filter(lot=lot).select_related('user').order_by('-timestamp')[:15]
            recent_chats = LotChatMessage.objects.filter(lot=lot).select_related('user').order_by('-timestamp')[:15]
            
            bids_list = [{'user': b.user.username, 'amount': float(b.amount), 'timestamp': b.timestamp.isoformat(), 'is_winning': b.is_winning} for b in recent_bids]
            chats_list = [{'user': c.user.username, 'message': c.message, 'timestamp': c.timestamp.isoformat()} for c in recent_chats]
            
            time_rem = lot.get_time_remaining().total_seconds() if lot.get_time_remaining() else None
            
            return {
                'current_bid': float(lot.current_bid), 'minimum_bid': float(lot.get_minimum_bid()),
                'status': lot.status, 'time_remaining': time_rem, 'bids': bids_list, 'chats': chats_list
            }
        except: return {'error': 'Lot not found'}
