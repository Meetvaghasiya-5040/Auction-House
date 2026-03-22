from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from auction_list.models import Auction, Lot
from bids.models import Bid
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from auction_list.models import Lot
from bids.models import Bid

@staff_member_required
def admin_moderation(request):
    """
    Live Moderation dashboard.
    Fetches the currently active lots so the admin can monitor bids and chats in real time.
    """

    live_lots = (
        Lot.objects
        .filter(status='active')
        .select_related(
            'auction',
            'winning_bidder',
            'invoice',
            'delivery'
        )
        .prefetch_related(
            'items',          # ManyToMany
            'bids',           # reverse FK
            'chat_messages'   # reverse FK
        )
        .order_by('lot_number')
    )

    # Optimized recent bids query
    recent_bids = (
        Bid.objects
        .filter(lot__status='active')
        .select_related('lot', 'user')
        .order_by('-timestamp')[:50]
    )

    context = {
        'live_lots': live_lots,
        'recent_bids': recent_bids,
    }

    return render(request, 'admin_panel/moderation.html', context)

@staff_member_required
def delete_bid_ajax(request, bid_id):
    """
    AJAX endpoint to delete a fraudulent bid.
    """
    if request.method == 'POST':
        try:
            bid = Bid.objects.get(id=bid_id)
            lot = bid.lot
            
            # Save the bid amount before deleting for the broadcast
            deleted_amount = bid.amount
            bid.delete()
            
            # Recalculate current price for the lot
            highest_bid = lot.bids.order_by('-amount').first()
            if highest_bid:
                lot.current_bid = highest_bid.amount
                lot.winning_bidder = highest_bid.user
            else:
                lot.current_bid = lot.starting_bid
                lot.winning_bidder = None
            lot.save()
            
            # Trigger a re-broadcast to the clients viewing that lot so their UI goes down
            from bids.utils import broadcast_bid_update
            broadcast_bid_update(lot)
            
            return JsonResponse({
                'success': True, 
                'new_price': float(lot.current_bid),
                'message': f'Bid of ₹{deleted_amount} was removed.'
            })
            
        except Bid.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Bid not found.'})
            
    return JsonResponse({'success': False, 'error': 'Invalid method.'}, status=405)
