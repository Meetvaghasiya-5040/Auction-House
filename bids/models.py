from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db import transaction


class Wallet(models.Model):
    """User wallet for managing bidding funds"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username}'s Wallet - ₹{self.balance}"
    
    def add_funds(self, amount, description="Funds added"):
        """Add funds to wallet"""
        if amount <= 0:
            raise ValidationError("Amount must be positive")
        
        self.balance = Decimal(str(self.balance)) + Decimal(str(amount))
        self.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=self,
            transaction_type='deposit',
            amount=amount,
            description=description
        )
        return self.balance
    
    def deduct_funds(self, amount, description="Funds deducted"):
        """Deduct funds from wallet"""
        if amount <= 0:
            raise ValidationError("Amount must be positive")
        
        if self.balance < Decimal(str(amount)):
            raise ValidationError("Insufficient balance")
        
        self.balance = Decimal(str(self.balance)) - Decimal(str(amount))
        self.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=self,
            transaction_type='deduction',
            amount=-amount,
            description=description
        )
        return self.balance
    
    def has_sufficient_balance(self, amount):
        """Check if wallet has sufficient balance"""
        return self.balance >= Decimal(str(amount))


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
    
    def save(self, *args, **kwargs):
        """Override save to update lot and create transaction"""
        is_new = self.pk is None
        
        if is_new:
            # Run validation
            self.full_clean()
            
            with transaction.atomic():
                previous_winner_bid = Bid.objects.filter(lot=self.lot, is_winning=True).first()
                
                if previous_winner_bid:
                    if previous_winner_bid.user == self.user:
                        previous_winner_bid.is_winning = False
                        previous_winner_bid.save()
                    else:
                        previous_winner_bid.is_winning = False
                        previous_winner_bid.save()
                
                # 3. This bid is now winning
                self.is_winning = True
                
                # 4. Update lot current bid and stats
                self.lot.current_bid = self.amount
                self.lot.winning_bidder = self.user
                self.lot.last_bid_time = timezone.now()
                self.lot.idle_timer_started = False  # Reset idle timer
                self.lot.save(update_fields=['current_bid', 'last_bid_time', 'idle_timer_started', 'winning_bidder'])

        super().save(*args, **kwargs)
        
        if is_new:
            # Broadcast bid update via WebSocket
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'lot_{self.lot.id}',
                    {
                        'type': 'bid_update',
                        'bid': {
                            'user': self.user.username,
                            'amount': float(self.amount),
                            'current_bid': float(self.lot.current_bid),
                            'minimum_bid': float(self.lot.get_minimum_bid()),
                            'timestamp': self.timestamp.isoformat(),
                            'is_winning': self.is_winning
                        }
                    }
                )
            
            # Update hot status for lot and auction
            from auction_list.utils import update_lot_hot_status, update_hot_status, get_hot_bid_count
            
            lot_is_hot = update_lot_hot_status(self.lot)
            auction_is_hot = update_hot_status(self.lot.auction)
            hot_bid_count = get_hot_bid_count(self.lot)
            
            # Broadcast hot status update if changed
            if channel_layer and (lot_is_hot or auction_is_hot):
                async_to_sync(channel_layer.group_send)(
                    f'lot_{self.lot.id}',
                    {
                        'type': 'hot_status_update',
                        'lot_is_hot': lot_is_hot,
                        'auction_is_hot': auction_is_hot,
                        'hot_bid_count': hot_bid_count
                    }
                )



class Transaction(models.Model):
    """Wallet transaction history"""
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('deduction', 'Deduction'),
        ('bid_placed', 'Bid Placed'),
        ('bid_refund', 'Bid Refund'),
        ('winning_payment', 'Winning Payment'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    related_bid = models.ForeignKey(Bid, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['wallet', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.wallet.user.username} - {self.get_transaction_type_display()} - ₹{self.amount}"


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

