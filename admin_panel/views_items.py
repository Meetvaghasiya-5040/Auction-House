from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from auction_list.models import Item
import json

@staff_member_required
def admin_items(request):
    """
    List view for all items submitted by users.
    Supports search by title/owner and status filter.
    """
    q        = request.GET.get('q', '').strip()
    status   = request.GET.get('status', '')
    category = request.GET.get('category', '')

    items = Item.objects.select_related('owner', 'item_catagory').order_by('-created_at')

    if q:
        from django.db.models import Q
        items = items.filter(
            Q(title__icontains=q) |
            Q(owner__username__icontains=q)
        )

    if status:
        items = items.filter(status=status)
        
    if category:
        items = items.filter(item_catagory_id=category)

    pending_count = Item.objects.filter(status='Pending Approval').count()
    
    from auction_list.models import Catagory
    categories = Catagory.objects.all()

    context = {
        'items': items,
        'pending_count': pending_count,
        'q': q,
        'status': status,
        'category': category,
        'categories': categories,
        'status_choices': Item.STATUS_CHOICES,
    }
    return render(request, 'admin_panel/items.html', context)

@staff_member_required
def update_item_status(request, item_id):
    """
    AJAX endpoint to Approve or Reject an item.
    """
    if request.method == 'POST':
        item = get_object_or_404(Item, id=item_id)
        data = json.loads(request.body)
        new_status = data.get('status')
        
        valid_statuses = ['Draft', 'Pending Approval', 'Approved', 'Pickup Item', 'Warehouse', 'Rejected', 'Assigned to Lot']
        
        if new_status in valid_statuses:
            item.status = new_status
            
            # Trigger Email Notifications
            if new_status == 'Pickup Item':
                from auction_list.email_notifications import send_pickup_confirmed_email
                send_pickup_confirmed_email(item)
            elif new_status == 'Warehouse':
                from auction_list.email_notifications import send_item_at_warehouse_email
                send_item_at_warehouse_email(item)
                
            item.save()  # triggers signal -> AdminNotification + WS broadcast
            return JsonResponse({'success': True, 'status': item.status, 'status_display': item.get_status_display()})
            
        return JsonResponse({'success': False, 'error': 'Invalid status.'})
        
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

@staff_member_required
def admin_item_detail(request, item_slug):
    """
    Detailed view for a specific item submitted by a user.
    """
    item = get_object_or_404(Item, slug=item_slug)
    return render(request, 'admin_panel/item_detail.html', {'item': item})
