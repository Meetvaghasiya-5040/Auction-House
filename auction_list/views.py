
from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.contrib.admin.views.decorators import staff_member_required
from .models import Auction, Item, Lot, AuctionRegister, LotRegister, Catagory, LotChatMessage
from bids.models import Bid, Wallet
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.db import transaction
import json
from django.views.decorators.http import require_POST, require_GET




#     def __init__(self, *args, **kwargs):
#         canvas.Canvas.__init__(self, *args, **kwargs)
#         self._saved_page_states = []

#     def showPage(self):
#         self._saved_page_states.append(dict(self.__dict__))
#         self._startPage()

#     def save(self):
#         num_pages = len(self._saved_page_states)
#         for state in self._saved_page_states:
#             self.__dict__.update(state)
#             self.draw_page_number(num_pages)
#             canvas.Canvas.showPage(self)
#         canvas.Canvas.save(self)

#     def draw_page_number(self, page_count):
#         self.setFont("Helvetica", 9)
#         self.setFillColor(colors.grey)
#         # Footer
#         self.drawRightString(A4[0] - 30, 20, f"Page {self._pageNumber} of {page_count}")
#         self.drawString(
#             30, 20, f"Generated on {timezone.now().strftime('%d-%m-%Y at %H:%M')}"
#         )
#         # Header line
#         self.setStrokeColor(colors.HexColor("#2c3e50"))
#         self.setLineWidth(2)
#         self.line(30, A4[1] - 30, A4[0] - 30, A4[1] - 30)


def format_inr(amount):
    if not amount:
        return "Rs. 0"
    return f"Rs. {amount:,.2f}"


@login_required
def auctions_list(request):
    """List all auctions with filtering"""
    auctions = Auction.objects.all().select_related("created_by", "approved_by")

    if not request.user.is_staff:
        # Default filtering for non-staff
        base_filters = Q(status__in=["approved", "live", "scheduled", "completed"]) | Q(created_by=request.user) | Q(created_by__is_staff=True)
        auctions = auctions.filter(base_filters)

    # Check if any filters are applied
    # Filtering
    status_filter = request.GET.get("status")
    type_filter = request.GET.get("auction_type")
    search_query = request.GET.get("q")
    category_filter = request.GET.get("category")
    
    # If NO filters are applied, hide completed auctions by default
    if not any([status_filter, type_filter, search_query, category_filter]):
         auctions = auctions.exclude(status="completed")

    for auction in auctions:
        if auction.status in ["approved", "scheduled", "live"]:
            auction.update_auction_status()
            auction.save()

    live_count = auctions.filter(status="live").count()
    scheduled_count = auctions.filter(status="scheduled").count()
    approved_count = auctions.filter(status="approved").count()
    pending_count = auctions.filter(status="pending").count()
    completed_count = auctions.filter(status="completed").count()

    # Filtering
    status_filter = request.GET.get("status")
    type_filter = request.GET.get("auction_type")
    search_query = request.GET.get("q")
    category_filter = request.GET.get("category")

    if status_filter:
        auctions = auctions.filter(status=status_filter)
    
    if type_filter:
        if type_filter == 'timed':
            auctions = auctions.filter(is_timed=True)

    if category_filter:
        auctions = auctions.filter(lots__lot_catagory__id=category_filter).distinct()

    if search_query:
        auctions = auctions.filter(
            Q(title__icontains=search_query) | 
            Q(description__icontains=search_query)
        )

    context = {
        "auctions": auctions,
        "live_count": live_count,
        "scheduled_count": scheduled_count,
        "approved_count": approved_count,
        "pending_count": pending_count,
        "completed_count": completed_count,
    }
    return render(request, "auctions/auction_list.html", context)


@staff_member_required
def get_items_by_category(request):
    category_id = request.GET.get("category_id")
    items = Item.objects.filter(category_id=category_id)

    data = [{"id": i.id, "text": f"{i.title} - ₹{i.price} ({i.status})"} for i in items]
    return JsonResponse(data, safe=False)


@login_required
def auction_detail(request, auction_id):
    auction = Auction.objects.select_related("created_by", "approved_by").get(
        id=auction_id
    )
    register = AuctionRegister.objects.filter(
        user=request.user, auction=auction
    ).exists()

    lots = auction.lots.all().select_related("winning_bidder")
    total_lots = lots.count()
    active_lots = lots.filter(status="active").count()
    sold_lots = lots.filter(status="sold").count()


    if auction.start_date == timezone.now():
        Lot.status = "active"
        Lot.save()


    if auction.status in ["approved", "scheduled", "live"]:
        auction.update_auction_status()
        auction.save()

    if (
        auction.status == "live"
        and auction.start_date
        and timezone.now() >= auction.start_date
        and not getattr(auction, "email_sent", False)
    ):
        # Notify ALL registered users of this auction
        registrations = AuctionRegister.objects.filter(auction=auction,user=request.user)
        recipient_list = [reg.user.email for reg in registrations if reg.user.email]

        if recipient_list:
            send_mail(
                subject=f"Auction Started: {auction.title}",
                message=(
                    f"The auction '{auction.title}' has started!\n\n"
                    "Login now and start bidding on the lots."
                ),
                from_email='meetvaghasiya166@gmail.com',
                recipient_list=recipient_list,
                fail_silently=False,
            )

            auction.email_sent = True
            auction.save()

    context = {
        "auction": auction,
        "lots": lots,
        "total_lots": total_lots,
        "active_lots": active_lots,
        "sold_lots": sold_lots,
        "register": register,
    }
    return render(request, "auctions/auction_detail.html", context)


@login_required
def auction_register(request, auction_id):
    user = request.user
    register = AuctionRegister.objects.create(user=user, auction_id=auction_id)
    messages.success(request, "You have successfully registered for the auction.")
    return redirect("auction_detail", auction_id)


@login_required
def auction_unregister(request, auction_id):
    user = request.user
    AuctionRegister.objects.filter(user=user, auction=auction_id).delete()
    messages.success(request, "You have successfully unregistered from the auction.")
    return redirect("auction_detail", auction_id)


@login_required
def view_lots(request, auction_id=None):

    
    if auction_id:
        auction = Auction.objects.get(id=auction_id)
        lots = auction.lots.all().select_related("lot_catagory")
    else:
        auction = None
        lots = Lot.objects.all().select_related("lot_catagory", "auction")
    
    # Get all categories for the filter dropdown
    categories = Catagory.objects.all().order_by('name')
    
    # Apply filters
    category_filter = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    status_filter = request.GET.get('status')
    
    if category_filter:
        lots = lots.filter(lot_catagory_id=category_filter)
    
    if min_price:
        lots = lots.filter(current_bid__gte=Decimal(min_price))
    
    if max_price:
        lots = lots.filter(current_bid__lte=Decimal(max_price))
    
    if status_filter:
        lots = lots.filter(status=status_filter)

    return render(
        request,
        "lots/view_lot.html",
        {
            "lots": lots,
            "auction": auction,
            "categories": categories,
            "counts": (
                Lot.all_status_count() if hasattr(Lot, "all_status_count") else {}
            ),
        },
    )


@login_required
def lot_detail(request, lot_id):
    lot = Lot.objects.select_related("lot_catagory", "auction").get(id=lot_id)
    return render(request, "lots/lot_detail.html", {"lot": lot})



@login_required
@require_POST
def place_bid(request, lot_id):
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount')))
        lot = Lot.objects.select_related('auction').get(id=lot_id)
        
        # Validation
        if lot.items.filter(owner=request.user).exists():
             return JsonResponse({'success': False, 'message': 'You cannot bid on your own lots/items.'})

        if lot.status != 'active':
             return JsonResponse({'success': False, 'message': 'Lot is not active'})
             
        # Prevent double bidding (consecutive bids by same user)
        if lot.winning_bidder == request.user:
             return JsonResponse({'success': False, 'message': 'You are already the highest bidder'})
             
        if lot.auction.status not in ['live', 'scheduled']:
             return JsonResponse({'success': False, 'message': 'Auction is not live'})

        min_bid = lot.get_minimum_bid()
        if amount < min_bid:
             return JsonResponse({'success': False, 'message': f'Bid must be at least ₹{min_bid}'})
             
        # Create Bid (Bid model handles wallet checks in .clean() or .save())
        try:
            with transaction.atomic():
                bid = Bid(
                    lot=lot,
                    user=request.user,
                    amount=amount
                )
                bid.save() # This will trigger validation and wallet deduction
                
                # Check for timed auction extension
                if lot.is_timed and lot.end_time:
                    time_remaining = (lot.end_time - timezone.now()).total_seconds()
                    if time_remaining < 60: # Extend if bid within last minute
                        lot.end_time += timezone.timedelta(minutes=2)
                        lot.save()

                return JsonResponse({
                    'success': True, 
                    'message': 'Bid placed successfully',
                    'new_balance': float(request.user.wallet.balance)
                })
                
        except ValidationError as e:
            return JsonResponse({'success': False, 'message': str(e.message)})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
@require_POST
def send_chat_message(request, lot_id):
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()
        
        if not message:
            return JsonResponse({'success': False, 'message': 'Message cannot be empty'})
            
        lot = Lot.objects.get(id=lot_id)
        
        chat = LotChatMessage.objects.create(
            lot=lot,
            user=request.user,
            message=message
        )
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
def get_lot_updates(request, lot_id):
    lot = Lot.objects.get(id=lot_id)
    
    # Get latest bids (last 10)
    latest_bids = Bid.objects.filter(lot=lot).select_related('user').order_by('-timestamp')[:10]
    bids_data = [{
        'user': bid.user.username,
        'amount': float(bid.amount),
        'timestamp': bid.timestamp.strftime('%H:%M:%S'),
        'is_winning': bid.is_winning
    } for bid in latest_bids]
    
    # Get latest chat (last 20)
    latest_chat = LotChatMessage.objects.filter(lot=lot).select_related('user').order_by('-timestamp')[:20]
    chat_data = [{
        'user': msg.user.username,
        'message': msg.message,
        'timestamp': msg.timestamp.strftime('%H:%M:%S')
    } for msg in latest_chat] # These are newest first
    # Idle Timer Logic
    idle_timeout = 15 # seconds before countdown starts
    countdown_duration = 5 # seconds of countdown
    
    countdown_val = None
    winner = None
    
    if lot.status == 'active':
        # 1. Check for Forced End Time (Timed Auction)
        if lot.is_timed and lot.end_time and timezone.now() >= lot.end_time:
             lot.close_lot()
             lot.refresh_from_db()
             winner = lot.winning_bidder.username if lot.winning_bidder else None

        # 2. Check for Idle Timeout (if applicable)
        elif lot.last_bid_time:
            time_since_bid = (timezone.now() - lot.last_bid_time).total_seconds()
            
            # Check if we are in countdown phase
            if time_since_bid > idle_timeout:
                 remaining_countdown = (idle_timeout + countdown_duration) - time_since_bid
                 
                 if remaining_countdown <= 0:
                     # Close the lot!
                     lot.close_lot()
                     lot.refresh_from_db()
                     winner = lot.winning_bidder.username if lot.winning_bidder else None
                 else:
                     countdown_val = remaining_countdown

    return JsonResponse({
        'current_bid': float(lot.current_bid),
        'min_next_bid': float(lot.get_minimum_bid()),
        'bid_count': lot.bids.count(),
        'status': lot.status,
        'bids': bids_data,
        'chat': chat_data,
        'time_remaining': lot.get_time_remaining().total_seconds() if lot.get_time_remaining() else None,
        'countdown': countdown_val,
        'winner': winner or (lot.winning_bidder.username if lot.winning_bidder else None),
        'user_balance': float(request.user.wallet.balance) if hasattr(request.user, 'wallet') else 0.00
    })


@require_GET
def get_auction_updates(request):
    """API to get real-time updates for auctions"""
    auction_ids = request.GET.get('ids', '').split(',')
    auction_ids = [int(id) for id in auction_ids if id.isdigit()]
    
    data = {}
    
    # 1. Individual Auction Statuses
    if auction_ids:
        auctions = Auction.objects.filter(id__in=auction_ids)
        for auction in auctions:
            # Trigger status update based on time
            if auction.status in ['scheduled', 'live', 'approved']:
                 auction.update_auction_status()
                 auction.save()

            data[auction.id] = {
                'status': auction.status,
                'status_display': auction.get_status_display(),
                'server_time': timezone.now().isoformat()
            }
            
    # 2. Global Counters (for Hero Section)
    data['global'] = {
        'live_count': Auction.objects.filter(status='live').count(),
        'total_count': Auction.objects.count()
    }
    
    return JsonResponse(data)
