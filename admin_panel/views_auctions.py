from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.contrib import messages
from auction_list.models import Auction, Lot, Item , Catagory
from django.utils import timezone
from django.utils.dateparse import parse_datetime
import json

@staff_member_required
def admin_auctions(request):
    """
    List view for all Auctions and Lots.
    Supports search by title and status filter.
    """
    q      = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')

    auctions = Auction.objects.all().order_by('-created_at')
    lots = Lot.objects.all().order_by('-end_time')
    categories = Catagory.objects.all()

    if q:
        auctions = auctions.filter(title__icontains=q)
        lots     = lots.filter(title__icontains=q)

    if status:
        auctions = auctions.filter(status=status)

    return render(request, 'admin_panel/auctions.html', {
        'auctions': auctions,
        'lots': lots,
        'categories': categories,
        'q': q,
        'status': status,
        'status_choices': Auction.STATUS_CHOICES,
    })

@staff_member_required
def auction_create(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        auction_type = request.POST.get('auction_type', 'live')
        location = request.POST.get('location', '').strip()
        terms = request.POST.get('terms_and_conditions', '').strip()
        min_bid_increment = request.POST.get('min_bid_increment', 100)
        buyer_premium = request.POST.get('buyer_premium_percentage', 0)
        allow_proxy = request.POST.get('allow_proxy_bidding') == 'on'
        status = request.POST.get('status', 'pending')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')

        if not title or not description:
            messages.error(request, 'Title and Description are required.')
            return render(request, 'admin_panel/auction_create.html')

        start_dt = parse_datetime(start_date) if start_date else None
        end_dt = parse_datetime(end_date) if end_date else None

        if start_dt:
            start_dt = timezone.make_aware(start_dt)

        if end_dt:
            end_dt = timezone.make_aware(end_dt)

        auction = Auction.objects.create(
            title=title,
            description=description,
            auction_type=auction_type,
            location=location,
            terms_and_conditions=terms,
            min_bid_increment=min_bid_increment,
            buyer_premium_percentage=buyer_premium,
            allow_proxy_bidding=allow_proxy,
            status=status,
            start_date=start_dt,
            end_date=end_dt,
            created_by=request.user,
        )
        auction.save()

        messages.success(request, f'Auction "{auction.title}" created successfully!')
        return redirect('admin_panel:auctions')

    return render(request, 'admin_panel/auction_create.html')


@staff_member_required
def fetch_available_items(request):
    """
    AJAX endpoint to fetch items eligible for lot creation.
    Items are eligible if they are Approved, Pickup Item, or Warehouse status
    and not already assigned to an active lot.
    """
    category_id = request.GET.get('category_id')

    # All statuses that mean the item is ready to be put in a lot
    eligible_statuses = ['Approved', 'Pickup Item', 'Warehouse', 'Pending Approval']

    items = Item.objects.filter(status__in=eligible_statuses)

    if category_id:
        items = items.filter(item_catagory_id=category_id)

    items_data = []
    for item in items:
        try:
            image_urls = item.get_image_urls
            image = image_urls[0] if image_urls else ''
        except Exception:
            image = ''
        try:
            reserve = str(item.reserve_price)
        except Exception:
            reserve = '0'

        items_data.append({
            'id': str(item.id),
            'title': item.title,
            'owner': item.owner.username,
            'estimate': str(item.estimated_value),
            'reserve': reserve,
            'status': item.status,
            'category': item.item_catagory.name if item.item_catagory else '—',
            'description': (item.description[:120] + '…') if item.description and len(item.description) > 120 else (item.description or ''),
            'image': image,
        })
    return JsonResponse({'items': items_data})



@staff_member_required
def toggle_auction_status(request, auction_id):
    """
    Quickly toggle an auction live or pending.
    """
    if request.method == 'POST':
        auction = get_object_or_404(Auction, id=auction_id)
        data = json.loads(request.body)
        new_status = data.get('status')
        
        valid_actions = ['pending', 'live', 'completed', 'cancelled', 'approved']
        if new_status in valid_actions:
            try:
                if new_status == 'live':
                    auction.go_live()
                elif new_status == 'completed':
                    auction.complete()
                elif new_status == 'cancelled':
                    auction.cancel()
                elif new_status == 'pending':
                    auction.submit_for_approval()
                elif new_status == 'approved':
                    auction.approve(request.user)
                return JsonResponse({'success': True, 'status': auction.status})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
            
        return JsonResponse({'success': False, 'error': 'Invalid status.'})
        
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

@staff_member_required
def create_lot_ajax(request):
    """
    Creates a new Lot binding an Item to an Auction from the dynamic interface.
    """
    if request.method == 'POST':
        data = json.loads(request.body)
        item_id = data.get('item_id')
        auction_id = data.get('auction_id')

        if not item_id or not auction_id:
            return JsonResponse({'success': False, 'error': 'Item and Auction are required'})

        eligible_statuses = ['Approved', 'Pickup Item', 'Warehouse', 'Pending Approval']

        try:
            item = Item.objects.get(id=item_id, status__in=eligible_statuses)
            auction = Auction.objects.get(id=auction_id)
            # Create Lot securely using structured backend logic
            new_lot = Lot.create_from_item(auction=auction, item=item)

            return JsonResponse({'success': True, 'lot_id': str(new_lot.id)})

        except Item.DoesNotExist:
            return JsonResponse({'success': False, 'error': f'Item #{item_id} not found or not eligible for lot creation.'})
        except Auction.DoesNotExist:
            return JsonResponse({'success': False, 'error': f'Auction #{auction_id} not found.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)


@staff_member_required
def auction_history(request):
    """
    Shows all ended (completed/cancelled) auctions.
    """
    ended_auctions = Auction.objects.filter(
        status__in=['completed', 'cancelled']
    ).order_by('-updated_at')

    return render(request, 'admin_panel/auction_history.html', {
        'ended_auctions': ended_auctions,
    })


@staff_member_required
def auction_edit(request, auction_id):
    """
    Edit an auction.  Locked (read-only) once it goes live or is completed.
    """
    auction = get_object_or_404(Auction, id=auction_id)
    is_locked = auction.status in ['live', 'completed', 'scheduled', 'cancelled']

    if request.method == 'POST':
        if is_locked:
            messages.error(request, 'Cannot edit a live, completed, or cancelled auction.')
            return redirect('admin_panel:auction_edit', auction_id=auction_id)

        auction.title = request.POST.get('title', auction.title).strip()
        auction.description = request.POST.get('description', auction.description).strip()
        auction.location = request.POST.get('location', '').strip()
        auction.terms_and_conditions = request.POST.get('terms_and_conditions', '').strip()
        auction.min_bid_increment = request.POST.get('min_bid_increment', auction.min_bid_increment)
        auction.buyer_premium_percentage = request.POST.get('buyer_premium_percentage', auction.buyer_premium_percentage)
        auction.allow_proxy_bidding = request.POST.get('allow_proxy_bidding') == 'on'

        start_date_raw = request.POST.get('start_date')
        end_date_raw = request.POST.get('end_date')
        if start_date_raw:
            sd = parse_datetime(start_date_raw)
            auction.start_date = timezone.make_aware(sd) if sd and timezone.is_naive(sd) else sd
        if end_date_raw:
            ed = parse_datetime(end_date_raw)
            auction.end_date = timezone.make_aware(ed) if ed and timezone.is_naive(ed) else ed

        auction.save()
        messages.success(request, f'Auction "{auction.title}" updated successfully!')
        return redirect('admin_panel:auctions')

    return render(request, 'admin_panel/auction_edit.html', {
        'auction': auction,
        'is_locked': is_locked,
    })


@staff_member_required
def auction_delete(request, auction_id):
    """
    Delete an auction (POST only). Cannot delete live auctions.
    """
    auction = get_object_or_404(Auction, id=auction_id)

    if request.method == 'POST':
        if auction.status == 'live':
            messages.error(request, 'Cannot delete a live auction. End it first.')
            return redirect('admin_panel:auctions')

        title = auction.title
        auction.delete()
        messages.success(request, f'Auction "{title}" has been deleted.')
        return redirect('admin_panel:auctions')

    # GET → show confirmation page
    return render(request, 'admin_panel/auction_delete.html', {'auction': auction})
