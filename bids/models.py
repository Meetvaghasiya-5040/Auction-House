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
        
        # Check wallet balance
        wallet = getattr(self.user, 'wallet', None)
        if not wallet:
            raise ValidationError("User does not have a wallet")
        
        # Calculate required funds
        # If user is already the winning bidder, they only need to pay the difference
        current_winning_bid = self.lot.bids.filter(is_winning=True).first()
        required_amount = self.amount

        if current_winning_bid and current_winning_bid.user == self.user:
             # Top-Up Scenario: Need (New Bid - Old Bid)
             # But if for some reason new bid < old bid (shouldn't happen due to min_bid check), logic still holds mathematically
             required_amount = self.amount - current_winning_bid.amount
        else:
             # New Bidder Scenario: Need full amount. 
             # (Refunds for previous winners happen AFTER this bid is accepted, so we don't count them for THIS user)
             pass
        
        if wallet.balance < Decimal(str(required_amount)):
            raise ValidationError(f"Insufficient wallet balance. You need ₹{required_amount} more.")
    
    def save(self, *args, **kwargs):
        """Override save to update lot and create transaction"""
        is_new = self.pk is None
        
        if is_new:
            # Run validation
            self.full_clean()
            
            with transaction.atomic():
                # Lock lot to prevent race conditions (optional but good practice)
                # self.lot.refresh_from_db() 

                previous_winner_bid = Bid.objects.filter(lot=self.lot, is_winning=True).first()
                deduction_amount = self.amount
                description = f"Bid placed on {self.lot.title}"
                
                if previous_winner_bid:
                    if previous_winner_bid.user == self.user:
                        # 1. Top-Up Scenario (User outbidding themselves)
                        deduction_amount = self.amount - previous_winner_bid.amount
                        description = f"Bid increased on {self.lot.title} (Top-up)"
                        
                        # Mark previous bid as not winning
                        previous_winner_bid.is_winning = False
                        previous_winner_bid.save()
                        
                    else:
                        # 2. Start-Over Scenario (New User outbidding someone else)
                        # Refund the previous winner
                        prev_wallet = previous_winner_bid.user.wallet
                        prev_wallet.add_funds(
                            amount=previous_winner_bid.amount,
                            description=f"Refund: Outbid on '{self.lot.title}'"
                        )
                        previous_winner_bid.is_winning = False
                        previous_winner_bid.save()
                        
                        # Use full amount for deduction
                        deduction_amount = self.amount
                
                # 3. This bid is now winning
                self.is_winning = True
                
                # 4. Update lot current bid and stats
                self.lot.current_bid = self.amount
                self.lot.winning_bidder = self.user
                self.lot.last_bid_time = timezone.now()
                self.lot.idle_timer_started = False  # Reset idle timer
                self.lot.save(update_fields=['current_bid', 'last_bid_time', 'idle_timer_started', 'winning_bidder'])
            
                # 5. Deduct funds from wallet
                # We do this AFTER invalidating previous bid to ensure 'Top-Up' logic uses correct state
                if deduction_amount > 0:
                     self.user.wallet.deduct_funds(
                        amount=deduction_amount,
                        description=description
                    )

        super().save(*args, **kwargs)
        
        if is_new and deduction_amount > 0:
            # Link transaction (Best effort lookup)
            latest_txn = Transaction.objects.filter(wallet=self.user.wallet).order_by('-timestamp').first()
            if latest_txn:
                latest_txn.related_bid = self
                latest_txn.transaction_type = 'bid_placed'
                latest_txn.save()


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
