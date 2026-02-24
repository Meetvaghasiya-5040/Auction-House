from django.core.management.base import BaseCommand
from auction_list.models import Auction, Lot


class Command(BaseCommand):
    help = 'Populate slug fields for existing Auction and Lot records'

    def handle(self, *args, **options):
       
        auctions_updated = 0
        for auction in Auction.objects.filter(slug__isnull=True):
            auction.slug = auction.generate_unique_slug()
            auction.save(update_fields=['slug'])
            auctions_updated += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully populated {auctions_updated} auction slugs')
        )
        
       
        lots_updated = 0
        for lot in Lot.objects.filter(slug__isnull=True):
            lot.slug = lot.generate_unique_slug()
            lot.save(update_fields=['slug'])
            lots_updated += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully populated {lots_updated} lot slugs')
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'Total: {auctions_updated + lots_updated} slugs generated')
        )
