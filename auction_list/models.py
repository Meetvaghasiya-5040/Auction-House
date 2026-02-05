from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from decimal import Decimal
from django.db import transaction
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from io import BytesIO
from xhtml2pdf import pisa
import uuid
import threading

class Catagory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    @property
    def total_items(self):
        """Get total items in this category"""
        return self.item_set.count()
    
    @property
    def available_items(self):
        """Get available items in this category"""
        return self.item_set.filter(status='available').count()

class Item(models.Model):
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    item_catagory = models.ForeignKey('Catagory', on_delete=models.CASCADE, null=True, blank=True)
    estimated_value = models.DecimalField(max_digits=10, decimal_places=2)
    images = models.JSONField(default=list, blank=True, help_text="List of image file paths")
    slug = models.SlugField(blank=True,unique=True)

    # Detailed description
    description = models.TextField(blank=True)
    condition = models.CharField(max_length=100, blank=True, help_text="e.g., Excellent, Good, Fair")
    dimensions = models.CharField(max_length=200, blank=True, help_text="e.g., 10x5x3 inches")
    weight = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="In kg")
    
    # Status tracking
    STATUS_CHOICES = [
        ('Available', 'In Warehouse'),
        ('Lotted', 'Assigned to Auction'),
        ('Sold', 'Sold'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'item_catagory']),
        ]
    
    def __str__(self):
        return f"{self.title} - ₹{self.estimated_value} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_unique_slug()
        super().save(*args, **kwargs)

    def generate_unique_slug(self):
        base_slug = slugify(self.title)
        slug = base_slug
        num = 1
        while Item.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{num}"
            num += 1
        return slug
    

    @property
    def current_lot(self):
        """Get the lot this item is currently assigned to"""
        return self.lots.filter(status__in=['draft', 'active']).first()


class Auction(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('live', 'Live'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    AUCTION_TYPE_CHOICES = [
        ('live', 'Live Auction'),
        ('scheduled', 'Scheduled Auction'),
        ('timed', 'Timed Auction'),
    ]
    
    # Basic Info
    title = models.CharField(max_length=255)
    description = models.TextField()
    auction_type = models.CharField(max_length=20, choices=AUCTION_TYPE_CHOICES, default='live')
    
    # Creator & Approval
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_auctions')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_auctions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Dates
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Settings
    allow_proxy_bidding = models.BooleanField(default=True)
    buyer_premium_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    min_bid_increment = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    
    # Additional Info
    location = models.CharField(max_length=255, blank=True)
    terms_and_conditions = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'start_date']),
            models.Index(fields=['created_by', 'status']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    def clean(self):
        # Validate dates
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValidationError("End date must be after start date")
        
        # Scheduled auctions must have dates
        if self.auction_type == 'scheduled' and (not self.start_date or not self.end_date):
            raise ValidationError("Scheduled auctions must have start and end dates")
    
    def save(self, *args, **kwargs):
        # Auto-update status based on dates
        if self.status == 'approved':
            self.update_auction_status()
        
        # Set approved_at timestamp
        if self.status == 'approved' and not self.approved_at:
            self.approved_at = timezone.now()
        
        super().save(*args, **kwargs)
    
    def update_auction_status(self):
        """Update auction status based on current time"""
        now = timezone.now()
        old_status = self.status
        
        if self.auction_type == 'scheduled' and self.start_date and self.end_date:
            if now < self.start_date:
                self.status = 'scheduled'
            elif self.start_date <= now <= self.end_date:
                self.status = 'live'
            elif now > self.end_date:
                self.status = 'completed'
        elif self.status == 'approved' and not self.start_date:
            # If no start date, it's ready to go live manually
            self.status = 'approved'
        
        # Sync Lot Status
        if old_status != 'live' and self.status == 'live':
            # Auction just went live, activate all draft lots
            self.lots.filter(status='draft').update(status='active')
            
        # If auction just completed, mark unsold lots and items
        if old_status != 'completed' and self.status == 'completed':
            self._mark_unsold_items()
    
    def can_edit(self, user):
        """Check if user can edit this auction"""
        return (
            user.is_staff or 
            (self.created_by == user and self.status in ['draft', 'pending'])
        )
    
    def can_approve(self, user):
        """Check if user can approve this auction"""
        return user.is_staff and self.status == 'pending'
    
    def approve(self, admin_user):
        """Approve the auction"""
        if not admin_user.is_staff:
            raise ValidationError("Only staff can approve auctions")
        
        self.status = 'approved'
        self.approved_by = admin_user
        self.approved_at = timezone.now()
        self.update_auction_status()
        self.save()
    
    def _mark_unsold_items(self):
        """Mark unsold lots and items as available when auction completes"""
        # Get all lots in this auction
        lots = self.lots.all()
        
        for lot in lots:
            # If lot is not sold, mark it as unsold
            if lot.status not in ['sold']:
                lot.status = 'unsold'
                lot.save(update_fields=['status'])
                
                # Mark all items in this lot as available
                for item in lot.items.all():
                    if item.status != 'sold':
                        item.status = 'Available'
                        item.save(update_fields=['status'])
    
    def submit_for_approval(self):
        """Submit auction for admin approval"""
        if self.status == 'draft':
            self.status = 'pending'
            self.save()
    
    def go_live(self):
        """Manually set auction to live"""
        if self.status in ['approved', 'scheduled']:
            self.status = 'live'
            if not self.start_date:
                self.start_date = timezone.now()
            self.save()
    
    def complete(self):
        """Mark auction as completed"""
        if self.status == 'live':
            self.status = 'completed'
            if not self.end_date:
                self.end_date = timezone.now()
            self.save()
    
    def cancel(self):
        """Cancel the auction"""
        if self.status not in ['completed', 'cancelled']:
            self.status = 'cancelled'
            self.save()
    
    @property
    def is_live(self):
        return self.status == 'live'
    
    @property
    def is_scheduled(self):
        return self.status == 'scheduled'
    
    @property
    def time_until_start(self):
        """Get time until auction starts"""
        if self.start_date and self.start_date > timezone.now():
            return self.start_date - timezone.now()
        return None
    
    @property
    def time_until_end(self):
        """Get time until auction ends"""
        if self.end_date and self.end_date > timezone.now():
            return self.end_date - timezone.now()
        return None
    
    @property
    def total_lots(self):
        """Get total number of lots in this auction"""
        return self.lots.count()
    
    @property
    def total_value(self):
        """Calculate total starting value of all lots"""
        from django.db.models import Sum
        return self.lots.aggregate(Sum('starting_bid'))['starting_bid__sum'] or 0


class Lot(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('sold', 'Sold'),
        ('unsold', 'Unsold'),
    ]
    
    # Core Information
    auction = models.ForeignKey('Auction', on_delete=models.CASCADE, related_name='lots')
    lot_number = models.IntegerField()  # Sequential number within auction
    title = models.CharField(max_length=255)
    description = models.TextField()
    
    # Items in this lot
    lot_catagory = models.ForeignKey('Catagory',on_delete=models.CASCADE,blank=True)
    items = models.ManyToManyField('Item', related_name='lots', blank=True)
    
    # Pricing
    starting_bid = models.DecimalField(max_digits=10, decimal_places=2,default=0.00)
    reserve_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, 
                                       help_text="Minimum price for sale (optional)")
    current_bid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Status & Winner
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    winning_bidder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                       related_name='won_lots')
    
    # Timed Auction Fields
    is_timed = models.BooleanField(default=False, help_text="Is this a timed auction lot?")
    end_time = models.DateTimeField(null=True, blank=True, help_text="When the timed auction ends")
    last_bid_time = models.DateTimeField(null=True, blank=True, help_text="Time of last bid")
    idle_timer_started = models.BooleanField(default=False, help_text="Has the idle timer started?")
    idle_timer_start_time = models.DateTimeField(null=True, blank=True, help_text="When idle timer started")
    min_bid_increment = models.DecimalField(max_digits=10, decimal_places=2, default=100.00, 
                                           help_text="Minimum bid increment")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional Information
    notes = models.TextField(blank=True, help_text="Internal notes (not visible to bidders)")
    
    class Meta:
        ordering = ['auction', 'lot_number']
        unique_together = ['auction', 'lot_number']
        indexes = [
            models.Index(fields=['auction', 'status']),
            models.Index(fields=['lot_number']),
        ]
    
    def __str__(self):
        return f"Lot {self.lot_number} - {self.title} ({self.auction.title})"
    
    def item_count(self):
        return self.items.count()
    item_count.short_description = 'Total items'

    @classmethod
    def all_status_count(cls):
        data={}
        for key,label in cls.STATUS_CHOICES:
            data[key]=cls.objects.filter(status = key).count()
        return data
    
    @property
    def recent_bids(self):
        """Get recent bids for initial template render"""
        return self.bids.filter(lot=self).select_related('user').order_by('-timestamp')[:20]

    def get_minimum_bid(self):
        """Get the minimum bid amount for this lot"""
        if self.current_bid > 0:
            increment = Decimal(str(self.min_bid_increment))
            bid_count = self.bids.count()
            
            # Tier-based increment system
            if bid_count >= 20:
                # After 20 bids: 1.3x multiplier
                increment = increment * Decimal("1.3")
            elif bid_count >= 10:
                # After 10 bids (11-20): 1.2x multiplier
                increment = increment * Decimal("1.2")
            # else: First 10 bids use base increment (1.0x)
                
            return self.current_bid + increment
        return self.starting_bid

    def get_current_increment(self):
        """Get the current increment amount based on bid count"""
        increment = self.min_bid_increment
        
        # Use same tiered logic if bids exist
        if self.current_bid > 0:
            bid_count = self.bids.count()
            if bid_count >= 20:
                increment = increment * Decimal("1.3")
            elif bid_count >= 10:
                increment = increment * Decimal("1.2")
        
        return increment
    
    def is_auction_ended(self):
        """Check if the auction has ended"""
        if self.status in ['sold', 'unsold']:
            return True
            
        # 1. Timed Auction
        if self.is_timed and self.end_time:
            return timezone.now() >= self.end_time
            
        # 2. General Auction End Date Fallback
        if self.auction.end_date:
            return timezone.now() >= self.auction.end_date
            
        return False
    
    def get_time_remaining(self):
        """Get time remaining for timed auction"""
        target_time = None
        
        if self.is_timed and self.end_time:
            target_time = self.end_time
        elif self.auction.end_date:
            target_time = self.auction.end_date
            
        if target_time:
            remaining = target_time - timezone.now()
            if remaining.total_seconds() > 0:
                return remaining
        return None
    
    def close_lot(self):
        """Close the lot, determine winner, and distribute funds"""


        if self.status != 'active':
            return False

        from bids.models import Bid, Wallet, AdminWallet  # Import locally to avoid circular import

        with transaction.atomic():
            # Find high bidder from Bids
            highest_bid = Bid.objects.filter(lot=self).order_by('-amount').first()
            
            if highest_bid:
                self.status = 'sold'
                self.winning_bidder = highest_bid.user
                highest_bid.is_winning = True 
                highest_bid.save()
                
                # Update items status to Sold
                items = self.items.all()
                total_estimated_value = sum(item.estimated_value for item in items)
                winning_amount = Decimal(str(self.current_bid))
                
                # 1. Admin Commission (10%)
                admin_commission = winning_amount * Decimal("0.10")
                
                # Credit Admin Wallet
                admin_wallet = AdminWallet.load()
                admin_wallet.add_funds(
                    amount=admin_commission,
                    description=f"Commission for Lot #{self.id}"
                )
                
                # 2. Distributable Amount
                distributable_amount = winning_amount - admin_commission
                
                for item in items:
                    item.status = 'Sold'
                    item.save()
                    
                    # 3. Calculate User Share
                    if total_estimated_value > 0:
                        share_percentage = item.estimated_value / total_estimated_value
                        user_share = share_percentage * distributable_amount
                        
                        # Credit Owner Wallet
                        wallet, created = Wallet.objects.get_or_create(user=item.owner)
                        wallet.add_funds(
                            amount=user_share, 
                            description=f"Sale payout for '{item.title}' (Lot #{self.id})"
                        )
                
                # --- GENERATE INVOICE & SEND EMAIL (ASYNC) ---
                try:
                    with transaction.atomic():
                        # Create Invoice (Fast)
                        invoice = Invoice.objects.create(
                            user=self.winning_bidder,
                            lot=self,
                            amount=winning_amount,
                            invoice_number=f"INV-{self.id}-{uuid.uuid4().hex[:8].upper()}",
                            status='paid' 
                        )
                        
                        # Spawn background thread for PDF & Email
                        threading.Thread(target=send_invoice_email_task, args=(invoice.id,)).start()
                        print(f"Started async invoice email task for Invoice #{invoice.id}")

                except Exception as e:
                    print(f"Error creating invoice object: {e}")
                    # Log error but don't fail the transaction if invoice creation fails? 
                    # Actually invoice creation IS critical, so we catch generally but it's part of transaction.
                    # If this block fails, transaction rolls back.
                    # but should log it.
                    
            else:
                self.status = 'unsold'
                
            self.save()
            return True


class AuctionRegister(models.Model):
    auction = models.ForeignKey('Auction', on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_registrations')
    registered_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} registered for {self.auction.title}"  


class LotRegister(models.Model):
    lot = models.ForeignKey('Lot', on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lot_registrations')
    registered_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} registered for {self.lot.title}"  

class LotChatMessage(models.Model):
    lot = models.ForeignKey('Lot', on_delete=models.CASCADE, related_name='chat_messages')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['timestamp']
        
    def __str__(self):
        return f"{self.user.username}: {self.message[:20]}"

class Invoice(models.Model):
    """Invoice for won auctions"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    lot = models.OneToOneField('Lot', on_delete=models.CASCADE, related_name='invoice')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    invoice_number = models.CharField(max_length=50, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='paid', choices=[
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled')
    ])
    
    class Meta:
        ordering = ['-issued_at']
        
    def __str__(self):
        return f"Invoice #{self.invoice_number} - {self.user.username}"


def send_invoice_email_task(invoice_id):
    """Background task to generate PDF and send invoice email"""
    try:
        # Re-fetch objects to ensure thread safety
        invoice = Invoice.objects.select_related('user', 'lot', 'lot__auction').get(id=invoice_id)
        lot = invoice.lot
        items = lot.items.all()
        winning_amount = invoice.amount
        admin_commission = winning_amount * Decimal("0.10")
        
        # Prepare Email Context
        context = {
            'winner': invoice.user,
            'lot': lot,
            'auction': lot.auction,
            'items': items,
            'winning_bid': winning_amount,
            'admin_commission': admin_commission,
            'total_amount': winning_amount, 
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.issued_at.strftime("%B %d, %Y")
        }
        
        # Render Email HTML (Rich Design)
        email_html = render_to_string('bids/invoice_template.html', context)
        plain_message = strip_tags(email_html)
        
        # Render PDF HTML (Simple Design)
        try:
            pdf_html = render_to_string('bids/invoice_pdf.html', context)
            
            # Generate PDF
            pdf_buffer = BytesIO()
            pisa_status = pisa.CreatePDF(pdf_html, dest=pdf_buffer)
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
            pdf_error = pisa_status.err
        except Exception as e:
            print(f"PDF Generation Error: {e}")
            pdf_error = True
            pdf_content = None

        
        # Send Email
        email = EmailMultiAlternatives(
            subject=f"Invoice for Lot #{lot.lot_number}: {lot.title}",
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[invoice.user.email]
        )
        email.attach_alternative(email_html, "text/html")
        
        if not pdf_error and pdf_content:
            filename = f"Invoice_{invoice.invoice_number}.pdf"
            email.attach(filename, pdf_content, 'application/pdf')
        else:
            print(f"Skipping PDF attachment due to error")
            
        email.send(fail_silently=True)
        print(f"[Async] Invoice email sent to {invoice.user.email}")
        
    except Exception as e:
        print(f"[Async Error] Failed to send invoice email: {e}")
