from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db import transaction




class SecurityDeposit(models.Model):
    """Initial deposit required for users to be able to bid"""
    STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('active', 'Active'),
        ('returned', 'Returned'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='security_deposits')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=10000.00)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Security Deposit'
        verbose_name_plural = 'Security Deposits'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - ₹{self.amount} ({self.get_status_display()})"


class AdminWallet(models.Model):
    """Singleton wallet for collecting admin commissions"""
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk and AdminWallet.objects.exists():
            raise ValidationError('There can be only one AdminWallet instance')
        return super(AdminWallet, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def add_funds(self, amount, description="Commission"):
        self.balance = Decimal(str(self.balance)) + Decimal(str(amount))
        self.save()

    def __str__(self):
        return f"Admin Wallet - ₹{self.balance}"


class Bid(models.Model):
    """Bid placed on a lot"""
    lot = models.ForeignKey('auction_list.Lot', on_delete=models.CASCADE, related_name='bids')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bids')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_winning = models.BooleanField(default=False)
    is_auto_bid = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Bid'
        verbose_name_plural = 'Bids'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['lot', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - ₹{self.amount} on {self.lot.title}"
    
    def clean(self):
        """Validate bid before saving"""
        # Check if lot is active
        if self.lot.status != 'active':
            raise ValidationError("Cannot bid on inactive lot")
        
        # Check minimum bid
        minimum_bid = self.lot.get_minimum_bid()
        if self.amount < minimum_bid:
            raise ValidationError(f"Bid must be at least ₹{minimum_bid}")
        
        # Check security deposit
        active_deposit = SecurityDeposit.objects.filter(user=self.user, status='active').exists()
        if not active_deposit:
            raise ValidationError("You must pay the ₹10,000 security deposit before placing a bid.")
    
    def _trigger_proxy_bids(self):
        """
        Final robust trigger using on_commit and a thread to ensure context isolation.
        """
        import threading
        from bids.utils import fire_proxy_bids
        from django.db import transaction as django_db
        
        lot_id = self.lot_id
        def run_proxy():
            try:
                print(f"\n[PROXY TRIGGER] Bid {self.id} (Winner: {self.user.username}) -> Switching to Thread for Lot {lot_id}")
                fire_proxy_bids(lot_id)
            except Exception as e:
                print(f"[PROXY TRIGGER] Thread Error: {e}")
        
        # Use on_commit to ensure the DB has actually saved this bid before we look for it in the thread
        django_db.on_commit(lambda: threading.Thread(target=run_proxy, daemon=True).start())

    def save(self, *args, **kwargs):
        """Override save to update lot statistics"""
        is_new = self.pk is None
        
        if is_new:
            # Run validation
            self.full_clean()
            
            with transaction.atomic():
                previous_winner_bid = Bid.objects.filter(lot=self.lot, is_winning=True).first()
                if previous_winner_bid:
                    previous_winner_bid.is_winning = False
                    previous_winner_bid.save()
                
                self.is_winning = True
                self.lot.current_bid = self.amount
                self.lot.winning_bidder = self.user
                self.lot.last_bid_time = timezone.now()
                self.lot.idle_timer_started = False
                self.lot.save(update_fields=['current_bid', 'last_bid_time', 'idle_timer_started', 'winning_bidder'])

        super().save(*args, **kwargs)
        
        if is_new:
            # Trigger proxy bids for other users
            if not self.is_auto_bid:
                self._trigger_proxy_bids()
            
            # Broadcast updates (WebSockets etc.)
            self._broadcast_bid_updates()
            self._update_hot_status()

    def _broadcast_bid_updates(self):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from django.db import transaction as django_db
        
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        def do_broadcast():
            try:
                # Get fresh data but avoid deep relationship lookups if possible
                lot = self.lot
                current_bid_val = float(self.amount)
                
                bid_summary = {
                    'user': self.user.username,
                    'amount': current_bid_val,
                    'current_bid': float(lot.current_bid),
                    'minimum_bid': float(lot.get_minimum_bid()),
                    'timestamp': self.timestamp.isoformat(),
                    'is_winning': self.is_winning,
                    'bid_id': self.id,
                    'lot_id': lot.id,
                    'lot_title': lot.title,
                }

                # Calculate fields for frontend compatibility
                time_rem = None
                try:
                    rem = lot.get_time_remaining()
                    if rem: time_rem = rem.total_seconds()
                except: pass

                broadcast_data = {
                    'type': 'bid_update',
                    'bid': bid_summary,
                    'minimum_bid': bid_summary['minimum_bid'],
                    'bid_count': lot.bids.count(),
                    'time_remaining': time_rem
                }

                async_to_sync(channel_layer.group_send)(f'lot_{lot.id}', broadcast_data)
                async_to_sync(channel_layer.group_send)('admin_updates', {
                    'type': 'live_bid_update', 
                    'bid': bid_summary
                })
            except Exception as e:
                print(f"[WS Broadcast Error] Bid {self.id}: {e}")

        # If it's an automated bid, we're likely in a background thread already,
        # so we broadcast immediately but safely.
        # For manual bids, wait for the transaction to commit.
        if self.is_auto_bid:
            do_broadcast()
        else:
            django_db.on_commit(do_broadcast)

    def _update_hot_status(self):
        from auction_list.utils import update_lot_hot_status, update_hot_status, get_hot_bid_count
        lot_is_hot = update_lot_hot_status(self.lot)
        auction_is_hot = update_hot_status(self.lot.auction)
        if lot_is_hot or auction_is_hot:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(f'lot_{self.lot.id}', {
                    'type': 'hot_status_update',
                    'lot_is_hot': lot_is_hot,
                    'auction_is_hot': auction_is_hot,
                    'hot_bid_count': get_hot_bid_count(self.lot)
                })



class ProxyBid(models.Model):
    """Proxy / automatic bid: user sets max amount they are willing to pay.
    The system auto-bids on their behalf up to this limit."""
    lot = models.ForeignKey('auction_list.Lot', on_delete=models.CASCADE, related_name='proxy_bids')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proxy_bids')
    max_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                     help_text="Maximum amount user is willing to bid")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Any change to a proxy bid (activation, max_amount update) should trigger the engine
        self._trigger_proxy_engine()

    def _trigger_proxy_engine(self):
        """
        Runs the proxy bidding war in a separate thread.
        Uses on_commit for reliability.
        """
        import threading
        from bids.utils import fire_proxy_bids
        from django.db import transaction as django_db
        
        lot_id = self.lot_id
        def run_proxy():
            try:
                print(f"\n[PROXY TRIGGER] Proxy {self.id} Update -> Switching to Thread for Lot {lot_id}")
                fire_proxy_bids(lot_id)
            except Exception as e:
                print(f"[PROXY TRIGGER] Error: {e}")
        
        django_db.on_commit(lambda: threading.Thread(target=run_proxy, daemon=True).start())

    class Meta:
        verbose_name = 'Proxy Bid'
        verbose_name_plural = 'Proxy Bids'
        unique_together = ['lot', 'user']
        ordering = ['-max_amount']

    def __str__(self):
        return f"{self.user.username} proxy on {self.lot.title} — max ₹{self.max_amount}"


class PendingPayment(models.Model):
    """Track pending payments for auction winners with timeout"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    
    lot = models.ForeignKey('auction_list.Lot', on_delete=models.CASCADE, related_name='pending_payments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pending_payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_to_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="Payment deadline (3 days from creation)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempt_number = models.IntegerField(default=1, help_text="1 for first winner, 2 for second bidder")
    pin_verified = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Pending Payment'
        verbose_name_plural = 'Pending Payments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['lot', 'status']),
        ]
    
    def __str__(self):
        return f"Payment for Lot #{self.lot.lot_number} - {self.user.username} (Attempt {self.attempt_number})"
    
    def is_expired(self):
        """Check if payment has expired"""
        from django.utils import timezone
        return timezone.now() > self.expires_at and self.status == 'pending'
    
    def time_remaining(self):
        """Get time remaining for payment"""
        from django.utils import timezone
        if self.status != 'pending':
            return None
        remaining = self.expires_at - timezone.now()
        return remaining if remaining.total_seconds() > 0 else None


class Transaction(models.Model):
    """Record of financial activities for a user"""
    TRANSACTION_TYPES = [
        ("deposit", "Security Deposit"),
        ("deduction", "Deduction"),
        ("bid_placed", "Bid Placed"),
        ("bid_refund", "Bid Refund"),
        ("winning_payment", "Winning Payment"),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    related_bid = models.ForeignKey('Bid', on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.transaction_type} - ₹{self.amount}"


# ─────────────────────────────────────────────────────────────
# SELLER WALLET SYSTEM
# ─────────────────────────────────────────────────────────────

class UserWallet(models.Model):
    """Wallet for sellers to receive funds from sold items"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - ₹{self.balance}"

    def credit(self, amount, description):
        """Credit the wallet and log transaction"""
        with transaction.atomic():
            # Refresh from db to avoid race conditions if needed
            self.refresh_from_db()
            self.balance += Decimal(str(amount))
            self.save(update_fields=['balance', 'updated_at'])
            
            WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                transaction_type='credit',
                description=description
            )
            return self.balance

    def debit(self, amount, description):
        """Debit the wallet and log transaction. Raises ValueError if insufficient balance."""
        with transaction.atomic():
            self.refresh_from_db()
            if self.balance < Decimal(str(amount)):
                raise ValueError("Insufficient wallet balance")
            
            self.balance -= Decimal(str(amount))
            self.save(update_fields=['balance', 'updated_at'])
            
            WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                transaction_type='debit',
                description=description
            )
            return self.balance


class WalletTransaction(models.Model):
    """Log of all credits and debits to a UserWallet"""
    TRANSACTION_TYPES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    wallet = models.ForeignKey(UserWallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        prefix = "+" if self.transaction_type == 'credit' else "-"
        return f"{self.wallet.user.username} {prefix}₹{self.amount} ({self.description})"


class SellerBankAccount(models.Model):
    """Bank account details for seller withdrawals, linked to Razorpay Fund Account"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=20)
    account_holder_name = models.CharField(max_length=100)
    
    # Razorpay Integration Fields
    razorpay_contact_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_fund_account_id = models.CharField(max_length=100, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bank_name} - {self.account_number[-4:]} ({self.user.username})"


class WithdrawalRequest(models.Model):
    """Record of a seller requesting a payout from their wallet"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    bank_account = models.ForeignKey(SellerBankAccount, on_delete=models.SET_NULL, null=True, related_name='withdrawals')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Razorpay Payout ID
    razorpay_payout_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Failure reason if any
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Withdrawal #{self.id} for {self.user.username} - ₹{self.amount} ({self.get_status_display()})"
