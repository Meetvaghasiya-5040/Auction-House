from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.files.storage import default_storage
from django.contrib.auth import logout
from .models import Profile
from django.contrib.auth.models import User
from auction_list.models import Item, Catagory
from django.core.paginator import Paginator
from datetime import datetime


# Create your views here.
from django.core.paginator import Paginator


def logoutview(request):
    logout(request)
    messages.success(request, "Successfully Logged Out !")
    return redirect("login")


from bids.models import Bid, Transaction
from auction_list.models import Lot

def profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    # User's items
    item_list = Item.objects.filter(owner=request.user)
    
    # User's bids
    bids_list = Bid.objects.filter(user=request.user).select_related('lot', 'lot__auction').order_by('-timestamp')
    bids_paginator = Paginator(bids_list, 8)
    bids_page = request.GET.get('bids_page')
    bids = bids_paginator.get_page(bids_page)
    
    # User's transactions
    transaction_list = Transaction.objects.filter(wallet__user=request.user).order_by('-timestamp')
    paginator = Paginator(transaction_list, 8)  # Show 8 transactions per page
    trans_page = request.GET.get('trans_page')
    transactions = paginator.get_page(trans_page)
    
    # Won Items (Lots where user is winning bidder and status is sold)
    won_items = Lot.objects.filter(winning_bidder=request.user, status='sold').select_related('auction', 'lot_catagory')
    
    # Pending Payments (Lots won but maybe not paid? Logic TBD, for now just show won items)
    # Using won_items as pending for now if we don't have paid status
    
    context = {
        "profile": profile, 
        "item_list": item_list,
        "bids": bids,
        "transactions": transactions,
        "won_items": won_items
    }
    
    return render(request, "profile_page.html", context)


def edit_profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    if request.method == "POST":
        # Update User model fields
        user = request.user
        username = request.POST.get("username")
        email = request.POST.get("email")
        
        # Simple validation
        if username:
            user.username = username
        if email:
            user.email = email
        user.save()
        
        # Update Profile model fields
        if request.FILES.get("profile_image"):
            profile.profile_image = request.FILES.get("profile_image")
        
        theme_color = request.POST.get("theme_color")
        if theme_color:
            profile.theme_color = theme_color
            
        profile.bio = request.POST.get("bio", "")
        profile.phone_number = request.POST.get("phone_number", "")
        profile.address = request.POST.get("address", "")
        profile.website = request.POST.get("website", "")
            
        profile.save()
            
        messages.success(request, "Profile updated successfully!")
        return redirect("profile")
        
    return render(request, "edit_profile.html", {"profile": profile})



def add_item_view(request):
    if request.method == "POST":
        title = request.POST.get("title")
        catagory_id = request.POST.get("catagory")
        description = request.POST.get("description", "")
        
        estimated_value = request.POST.get("estimated_value")
        condition = request.POST.get("condition", "")
        dimensions = request.POST.get("dimensions", "")
        weight = request.POST.get("weight")
        
        selected_catagory = get_object_or_404(Catagory, id=catagory_id)
        
        images = request.FILES.getlist("image")
        images_paths = []
        
        for image in images:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{image.name}"
            image_path = default_storage.save(f"item_images/{filename}", image)
            images_paths.append(image_path)
        
        item = Item.objects.create(
            owner=request.user,
            title=title,
            item_catagory=selected_catagory,
            description=description,
            estimated_value=estimated_value,
            condition=condition,
            dimensions=dimensions,
            weight=weight if weight else None,
            images=images_paths,
            status='Available'  
        )
        
        messages.success(request, f'Item "{item.title}" has been added to your warehouse successfully!')
        
        return redirect("profile")
   
    context = {
        "catagories": Catagory.objects.all().order_by('name')
    }
    return render(request, "add_item.html", context)


def delete_item_view(request, item_id):
    item = get_object_or_404(Item, id=item_id, owner=request.user)
    if request.method == "POST":
        item.delete()
        return redirect("profile")


def edit_item_view(request, item_id):
    item = get_object_or_404(Item, id=item_id, owner=request.user)
    if request.method == "POST":
        item.title = request.POST.get("title")
        item.estimated_value = request.POST.get("estimated_value")
        item.item_catagory = get_object_or_404(
            Catagory, id=request.POST.get("catagory")
        )

        item.save()
        return redirect("profile")

    return render(
        request, "edit_item.html", {"item": item, "catagories": Catagory.objects.all()}
    )


def home_view(request):
    from django.db.models import Count
    from django.utils import timezone
    
        
    active_auctions = Lot.objects.filter(status='active').order_by('-created_at')[:6]
    
    now = timezone.now()
    ending_soon = Lot.objects.filter(
        status='active', 
        is_timed=True, 
        end_time__gt=now
    ).order_by('end_time')[:3]
    
    recently_sold = Lot.objects.filter(status='sold').select_related('winning_bidder').order_by('-last_bid_time')[:5]
    
    featured_lots = Lot.objects.filter(status='active').annotate(
        num_bids=Count('bids')
    ).order_by('-num_bids')[:3]

    from django.db.models import Sum    

    
    total_users_count = User.objects.count()

    volume_data = Lot.objects.filter(status='sold').aggregate(total_volume=Sum('current_bid'))
    total_volume = volume_data['total_volume'] or 0
    
    total_active_lots = Lot.objects.filter(status='active').count()
    
 
    categories = Catagory.objects.all()
    
    context = {
        'active_auctions': active_auctions,
        'ending_soon': ending_soon,
        'recently_sold': recently_sold,
        'featured_lots': featured_lots,
        'stats': {
            'users': total_users_count,
            'volume': total_volume,
            'active': total_active_lots
        },
        'categories': categories
    }
    
    return render(request, "home.html", context)


def item_detail(request, item_id, slug):
    item = get_object_or_404(Item, id=item_id, slug=slug)
    
    # Check if item is sold in a lot
    sold_lot = item.lots.filter(status='sold').first()
    
    context = {
        "item": item,
        "sold_lot": sold_lot
    }
    
    return render(request, "item_detail.html", context)
