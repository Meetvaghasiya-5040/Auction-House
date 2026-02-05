from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from decimal import Decimal
from .models import Wallet, Bid, Transaction
from auction_list.models import Lot, Invoice


@login_required
def wallet_dashboard(request):
    """Display user's wallet dashboard"""
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-timestamp')[:50]
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    return render(request, 'bids/wallet_dashboard.html', context)


@login_required
def add_funds(request):
    """Add funds to user's wallet"""
    if request.method == 'POST':
        amount = request.POST.get('amount')
        
        try:
            amount = Decimal(amount)
            if amount <= 0:
                messages.error(request, 'Amount must be positive')
                return redirect('add_funds')
            
            wallet, created = Wallet.objects.get_or_create(user=request.user)
            wallet.add_funds(amount, description=f"Funds added via wallet dashboard")
            
            messages.success(request, f'Successfully added ₹{amount} to your wallet')
            return redirect('wallet_dashboard')
            
        except (ValueError, TypeError):
            messages.error(request, 'Invalid amount')
            return redirect('add_funds')
    
    return render(request, 'bids/add_funds.html')


@login_required
def my_bids(request):
    """Display user's bid history"""
    bids = Bid.objects.filter(user=request.user).select_related('lot', 'lot__auction').order_by('-timestamp')
    
    # Separate active and completed bids
    active_bids = bids.filter(lot__status='active')
    completed_bids = bids.filter(lot__status__in=['sold', 'unsold'])
    
    context = {
        'active_bids': active_bids,
        'completed_bids': completed_bids,
    }
    return render(request, 'bids/my_bids.html', context)


@login_required
def won_lots(request):
    """Display lots won by user"""
    won_lots = Lot.objects.filter(winning_bidder=request.user).select_related('auction').order_by('-updated_at')
    
    context = {
        'won_lots': won_lots,
    }
    return render(request, 'bids/won_lots.html', context)


@login_required
def place_bid_api(request, lot_id):
    """API endpoint to place a bid (fallback for non-WebSocket)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})
    
    try:
        lot = get_object_or_404(Lot, id=lot_id)
        amount = Decimal(request.POST.get('amount', 0))
        
        # Get or create wallet
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        
        # Validate
        if lot.items.filter(owner=request.user).exists():
            return JsonResponse({'success': False, 'error': 'You cannot bid on your own lots/items.'})

        if lot.status != 'active':
            return JsonResponse({'success': False, 'error': 'Lot is not active'})

        # Prevent double bidding (consecutive bids by same user)
        if lot.winning_bidder == request.user:
            return JsonResponse({'success': False, 'error': 'You are already the highest bidder'})
        
        minimum_bid = lot.get_minimum_bid()
        if amount < minimum_bid:
            return JsonResponse({'success': False, 'error': f'Minimum bid is ₹{minimum_bid}'})
        
        if not wallet.has_sufficient_balance(amount):
            return JsonResponse({'success': False, 'error': f'Insufficient balance. Your balance: ₹{wallet.balance}'})
        
        # Create bid
        bid = Bid.objects.create(
            lot=lot,
            user=request.user,
            amount=amount
        )
        
        return JsonResponse({
            'success': True,
            'bid': {
                'id': bid.id,
                'amount': float(bid.amount),
                'user': bid.user.username,
                'timestamp': bid.timestamp.isoformat(),
            },
            'current_bid': float(lot.current_bid),
            'minimum_bid': float(lot.get_minimum_bid()),
            'wallet_balance': float(request.user.wallet.balance),
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def get_bid_updates(request, lot_id):
    """API endpoint for polling bid updates"""
    try:
        lot = Lot.objects.get(id=lot_id)
        
        # Auto-close logic
        time_remaining = lot.get_time_remaining()
        remaining_seconds = time_remaining.total_seconds() if time_remaining else 0
        
        # If time is up and lot is still active, close it
        if lot.status == 'active' and (lot.is_auction_ended() or (time_remaining is not None and remaining_seconds <= 0)):
            lot.close_lot()
            lot.refresh_from_db()
            
        # Serialize recent bids
        recent_bids = lot.recent_bids
        bids_data = []
        for bid in recent_bids:
            bids_data.append({
                'user': bid.user.username,
                'amount': float(bid.amount),
                'timestamp': bid.timestamp.isoformat(),
                'is_winning': bid.is_winning
            })
            
        # Serialize chats (optional, if we want to include chat in polling)
        # chats_data = ... 
        
        response_data = {
            'current_bid': float(lot.current_bid),
            'minimum_bid': float(lot.get_minimum_bid()),
            'time_remaining': remaining_seconds,
            'status': lot.status,
            'bids': bids_data,
            'bid_count': lot.bids.count(),
        }
        
        if lot.status == 'sold' and lot.winning_bidder:
            response_data['winner'] = lot.winning_bidder.username
            response_data['winning_bid'] = float(lot.current_bid)
            
        return JsonResponse(response_data)
        
    except Lot.DoesNotExist:
        return JsonResponse({'error': 'Lot not found'}, status=404)
    except Exception as e:
        print(f"Error in get_bid_updates: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def my_invoices(request):
    """List all invoices for the current user"""
    invoices = Invoice.objects.filter(user=request.user).select_related('lot', 'lot__auction').order_by('-issued_at')
    
    context = {
        'invoices': invoices
    }
    return render(request, 'bids/my_invoices.html', context)


@login_required
def invoice_detail(request, invoice_id):
    """Detailed view of a specific invoice"""
    # Import here or ensure top-level import (already added Invoice to top imports)
    invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)
    
    context = {
        'invoice': invoice,
        'lot': invoice.lot,
        'auction': invoice.lot.auction,
        'items': invoice.lot.items.all(),
        'user': request.user
    }
    return render(request, 'bids/invoice_detail.html', context)


