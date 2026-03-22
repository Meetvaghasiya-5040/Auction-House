from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.contrib.auth.models import User
from auction_list.models import Lot, Invoice

@staff_member_required
def admin_global_search(request):
    """
    Global search endpoint scanning Users, Lots, and Invoices.
    """
    q = request.GET.get('q', '').strip()
    
    users = []
    lots = []
    invoices = []
    
    if q:
        # 1. Search Users
        users = User.objects.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        ).order_by('-date_joined')[:10]  # Limit broadly
        
        # 2. Search Lots
        lots = Lot.objects.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(status__icontains=q)
        ).select_related('auction').order_by('-created_at')[:10]
        
        # 3. Search Invoices
        invoices = Invoice.objects.filter(
            Q(invoice_number__icontains=q) |
            Q(status__icontains=q) |
            Q(user__username__icontains=q) |
            Q(lot__items__owner__username__icontains=q)
        ).select_related('user', 'lot').prefetch_related('lot__items__owner').order_by('-issued_at')[:10]
        
    context = {
        'q': q,
        'users': users,
        'lots': lots,
        'invoices': invoices,
        'total_results': (len(users) + len(lots) + len(invoices)) if q else 0
    }
    
    return render(request, 'admin_panel/search_results.html', context)
