from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from auction_list.models import Item

@staff_member_required
def verification_dashboard(request):
    """Admin dashboard to view and approve items requiring document verification"""
    
    # Get all items pending approval
    pending_items = Item.objects.filter(status='Pending Approval').select_related('owner', 'item_catagory').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(pending_items, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Stats
    total_pending = pending_items.count()
    total_approved = Item.objects.filter(item_catagory__requires_document=True, status__in=['Available', 'Lotted', 'Sold']).count()
    
    context = {
        'page_obj': page_obj,
        'total_pending': total_pending,
        'total_approved': total_approved,
        'nav_active': 'verification' # For admin sidebar highlighting if any
    }
    
    return render(request, 'admin/verification_dashboard.html', context)

@staff_member_required
def approve_item(request, item_id):
    """Approve an item after verifying documents"""
    item = get_object_or_404(Item, id=item_id, status='Pending Approval')
    
    if request.method == 'POST':
        item.status = 'Available'
        item.save()
        messages.success(request, f"Item '{item.title}' has been approved and moved to the warehouse.")
        
        # Email notification to user can be added here
        
    return redirect('verification_dashboard')

@staff_member_required
def reject_item(request, item_id):
    """Reject an item (delete or mark as rejected)"""
    item = get_object_or_404(Item, id=item_id, status='Pending Approval')
    
    if request.method == 'POST':
        title = item.title
        # Delete it or we could add a 'Rejected' status
        item.delete() 
        messages.error(request, f"Item '{title}' has been rejected and removed.")
        
        # Email notification to user can be added here
        
    return redirect('verification_dashboard')
