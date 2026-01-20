from django.shortcuts import render
from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect
from django.core.files.storage import default_storage
from AuctionHouse import settings
from .models import Profile
from django.contrib.auth.models import User 
from auction_list.models import Item,Catagory
from django.shortcuts import render, get_object_or_404
from django.core.files.storage import FileSystemStorage


# Create your views here.

def logoutview(request):
    logout(request)
    messages.success(request, "Successfully Logged Out !")
    return redirect("login")
    

def profile_view(request):
    profile = get_object_or_404(Profile, user=request.user)
    item_list = Item.objects.filter(owner=request.user)
    return render(request, 'profile_page.html', {'profile': profile, 'item_list': item_list})

def add_item_view(request):
    if request.method == 'POST':
        item_name = request.POST.get('title')
        estimated_value = request.POST.get('estimated_value')
        selected_catagory = get_object_or_404(Catagory, id=request.POST.get('catagory'))
        images = request.FILES.getlist('image')

        
        images_paths = []

        for image in images:
            image_path = default_storage.save(f"item_images/{image.name}", image)
            images_paths.append(image_path)

        item=Item.objects.create(
            owner=request.user,
            title=item_name,
            estimated_value=estimated_value,
            item_catagory = selected_catagory,
            images=images_paths
            )
        print("files",request.FILES)
        
        item.save()
        return redirect('profile')
        
    return render(request, 'add_item.html',{'catagories':Catagory.objects.all()})


def delete_item_view(request, item_id):
    item = get_object_or_404(Item, id=item_id, owner=request.user)
    if request.method == 'POST':
        item.delete()
        return redirect('profile')


def edit_item_view(request, item_id):
    item = get_object_or_404(Item, id=item_id, owner=request.user)
    if request.method == 'POST':
        item.title = request.POST.get('title')
        item.estimated_value = request.POST.get('estimated_value')  
        item.item_catagory = get_object_or_404(Catagory, id=request.POST.get('catagory'))
        
        item.save()
        return redirect('profile')
    
    return render(request, 'edit_item.html', {'item': item, 'catagories':Catagory.objects.all()})
def home_view(request):
    return render(request, 'home.html')


def item_detail(request,item_id,slug):
    item = Item.objects.filter(id = item_id,slug = slug)
    return render(request,'item_detail.html',{'item':item})