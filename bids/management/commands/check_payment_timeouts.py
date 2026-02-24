from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from bids.models import PendingPayment, Bid, Wallet
from decimal import Decimal
from django.conf import settings


class Command(BaseCommand):
    help = 'Check for expired pending payments and handle cascading to second bidder or refunds'

    def handle(self, *args, **options):
        """
        Check for expired pending payments and:
        1. If attempt_number == 1: cascade to second highest bidder
        2. If attempt_number == 2: mark lot as unsold and refund all bidders
        """
        now = timezone.now()
        
        # Find all expired pending payments
        expired_payments = PendingPayment.objects.filter(
            status='pending',
            expires_at__lte=now
        ).select_related('lot', 'user')
        
        for payment in expired_payments:
            self.stdout.write(
                self.style.WARNING(
                    f'Processing expired payment for Lot #{payment.lot.lot_number} - User: {payment.user.username}'
                )
            )
            
            try:
                with transaction.atomic():
                    if payment.attempt_number == 1:
                        # First winner failed to pay, cascade to second bidder
                        self._cascade_to_second_bidder(payment)
                    elif payment.attempt_number == 2:
                        # Second bidder also failed, mark as unsold and refund all
                        self._mark_unsold_and_refund(payment)
                    else:
                        # Shouldn't happen, but mark as expired
                        payment.status = 'expired'
                        payment.save()
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing payment {payment.id}: {str(e)}'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Processed {expired_payments.count()} expired payments'
            )
        )
    
    def _cascade_to_second_bidder(self, payment):
        """Cascade lot to second highest bidder"""
        from datetime import timedelta
        
        lot = payment.lot
        
        # Mark first payment as expired
        payment.status = 'expired'
        payment.save()
        
        # Refund first winner
        first_winner_bid = Bid.objects.filter(
            lot=lot,
            user=payment.user,
            is_winning=True
        ).first()
        
        if first_winner_bid:
            first_winner_bid.is_winning = False
            first_winner_bid.save()
            
            # Refund the amount
            wallet = Wallet.objects.get(user=payment.user)
            wallet.add_funds(
                amount=first_winner_bid.amount,
                description=f"Refund: Payment timeout for Lot #{lot.lot_number}"
            )
        
        # Find second highest bidder
        second_bid = Bid.objects.filter(lot=lot).exclude(
            user=payment.user
        ).order_by('-amount').first()
        
        if second_bid:
            # Create pending payment for second bidder with centralized timeout
            expires_at = timezone.now() + timedelta(minutes=settings.WINNER_PAYMENT_TIMEOUT_MINUTES)
            
            PendingPayment.objects.create(
                lot=lot,
                user=second_bid.user,
                amount=second_bid.amount,
                expires_at=expires_at,
                attempt_number=2,
                status='pending'
            )
            
            # Update lot
            lot.winning_bidder = second_bid.user
            lot.current_bid = second_bid.amount
            second_bid.is_winning = True
            second_bid.save()
            lot.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cascaded Lot #{lot.lot_number} to second bidder: {second_bid.user.username}'
                )
            )
        else:
            # No second bidder, mark as unsold
            self._mark_unsold_and_refund(payment)
    
    def _mark_unsold_and_refund(self, payment):
        """Mark lot as unsold and refund all bidders"""
        lot = payment.lot
        
        # Mark payment as expired
        payment.status = 'expired'
        payment.save()
        
        # Mark lot as unsold
        lot.status = 'unsold'
        lot.save()
        
        # Refund all bidders who have winning bids
        all_bids = Bid.objects.filter(lot=lot, is_winning=True)
        
        for bid in all_bids:
            bid.is_winning = False
            bid.save()
            
            # Refund the amount
            try:
                wallet = Wallet.objects.get(user=bid.user)
                wallet.add_funds(
                    amount=bid.amount,
                    description=f"Refund: Lot #{lot.lot_number} unsold"
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Refunded ₹{bid.amount} to {bid.user.username}'
                    )
                )
            except Wallet.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f'Wallet not found for user {bid.user.username}'
                    )
                )
        
        # Mark all items as available
        for item in lot.items.all():
            if item.status != 'Sold':
                item.status = 'Available'
                item.save()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Marked Lot #{lot.lot_number} as unsold and refunded all bidders'
            )
        )
