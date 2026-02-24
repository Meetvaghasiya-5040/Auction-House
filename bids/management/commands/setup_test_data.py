from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from bids.models import Wallet
from auction_list.models import Auction, Lot, Catagory, Item

class Command(BaseCommand):
    help = 'Setup test data for browser verification'

    def handle(self, *args, **kwargs):
        self.stdout.write('Setting up test data...')

        # 1. Create Users
        admin, _ = User.objects.get_or_create(username='admin', defaults={'email': 'admin@example.com', 'is_staff': True, 'is_superuser': True})
        if _: admin.set_password('adminpassword'); admin.save()
        
        bidder1, _ = User.objects.get_or_create(username='bidder1', defaults={'email': 'bidder1@example.com'})
        if _: bidder1.set_password('password123'); bidder1.save()

        bidder2, _ = User.objects.get_or_create(username='bidder2', defaults={'email': 'bidder2@example.com'})
        if _: bidder2.set_password('password123'); bidder2.save()
        
        # 2. Setup Profiles/PINs (Assuming Profile model usage based on earlier context)
        # Try to set PIN if Profile exists
        for user in [admin, bidder1, bidder2]:
            try:
                if hasattr(user, 'profile'):
                    # Manually set a hashed PIN '1234'
                    # Since we don't have easy access to the exact hashing method used in views aside from check_password,
                    # we'll assume Django's default hasher is compatible or just set it if we can.
                    # Bids/views.py uses check_password, so we should store it hashed.
                    from django.contrib.auth.hashers import make_password
                    user.profile.transaction_pin = make_password('1234')
                    user.profile.save()
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not set PIN for {user.username}: {e}"))

        # 3. Wallets
        Wallet.objects.update_or_create(user=bidder1, defaults={'balance': Decimal('10000.00')})
        Wallet.objects.update_or_create(user=bidder2, defaults={'balance': Decimal('5000.00')})
        Wallet.objects.update_or_create(user=admin, defaults={'balance': Decimal('100000.00')})

        # 4. Auction
        cat, _ = Catagory.objects.get_or_create(name="Browser Test Category")
        
        auction, _ = Auction.objects.get_or_create(
            slug='browser-test-auction',
            defaults={
                'title': 'Browser Test Auction',
                'created_by': admin,
                'status': 'live',
                'start_date': timezone.now() - timedelta(hours=1),
                'end_date': timezone.now() + timedelta(days=1),
                'description': 'An auction for browser testing.',
                'auction_type': 'live'
            }
        )
        if _: self.stdout.write(f'Created Auction: {auction.title}')
        
        # Ensure it's live
        auction.status = 'live'
        auction.save()

        # 5. Lots
        # Lot 1: Active, low price
        item1, _ = Item.objects.get_or_create(
            title="Golden Watch",
            owner=admin,
            defaults={'estimated_value': 500, 'status': 'Lotted'}
        )
        
        lot1, created = Lot.objects.get_or_create(
            auction=auction,
            lot_number=1,
            defaults={
                'title': 'Golden Watch Lot',
                'lot_catagory': cat,
                'starting_bid': Decimal('100.00'),
                'min_bid_increment': Decimal('10.00'),
                'status': 'active'
            }
        )
        lot1.items.add(item1)
        if created: self.stdout.write(f'Created Lot 1: {lot1.title}')
        
        lot1.status = 'active'
        lot1.current_bid = Decimal('100.00')
        lot1.save()

        # Lot 2: Near end (for testing completion)
        # We can't easily auto-expire it without celery/cron, but we can set it up to be manually closed
        item2, _ = Item.objects.get_or_create(title="Silver Coin", owner=admin, defaults={'estimated_value': 200, 'status': 'Lotted'})
        lot2, _ = Lot.objects.get_or_create(
            auction=auction,
            lot_number=2,
            defaults={
                'title': 'Silver Coin Lot',
                'lot_catagory': cat,
                'starting_bid': Decimal('50.00'),
                'min_bid_increment': Decimal('5.00'),
                'status': 'active'
            }
        )
        lot2.items.add(item2)

        self.stdout.write(self.style.SUCCESS('Successfully setup test data.'))
        self.stdout.write('Users: bidder1 (pass: password123), bidder2 (pass: password123)')
        self.stdout.write('PIN for all: 1234')
