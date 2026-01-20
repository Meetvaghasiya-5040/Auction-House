from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.text import slugify

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
        ('withdrawn', 'Withdrawn'),
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
