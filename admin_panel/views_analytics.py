from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
import json

from auction_list.models import Auction, Lot, Item, Invoice
from bids.models import Bid, AdminWallet, SecurityDeposit


@staff_member_required
def admin_analytics(request):
    """Overall analytics dashboard for all auctions."""

    # ── Revenue ──────────────────────────────────────────
    admin_wallet = AdminWallet.load()
    total_wallet = admin_wallet.balance if admin_wallet else Decimal('0')

    invoices = Invoice.objects.filter(status='paid')
    total_bid_revenue   = invoices.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_premium_rev   = invoices.aggregate(s=Sum('buyer_premium'))['s'] or Decimal('0')
    total_shipping_rev  = invoices.aggregate(s=Sum('shipping_fee'))['s'] or Decimal('0')

    # ── Auction Status Breakdown ─────────────────────────
    auction_status_data = {}
    for key, label in Auction.STATUS_CHOICES:
        auction_status_data[label] = Auction.objects.filter(status=key).count()

    # ── Lots Status Breakdown ────────────────────────────
    lot_status_data = {}
    for key, label in Lot.STATUS_CHOICES:
        lot_status_data[label] = Lot.objects.filter(status=key).count()

    # ── Top Auctions by Revenue ──────────────────────────
    top_auctions = (
        Auction.objects
        .annotate(
            total_revenue=Sum('lots__invoice__amount'),
            total_premium=Sum('lots__invoice__buyer_premium'),
            sold_lots=Count('lots', filter=Q(lots__status='sold')),
        )
        .order_by('-total_revenue')[:5]
    )

    # ── Monthly Revenue Trend (last 6 months) ────────────
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = (timezone.now().replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end   = (month_start + timedelta(days=32)).replace(day=1)
        rev = invoices.filter(issued_at__gte=month_start, issued_at__lt=month_end).aggregate(
            s=Sum('amount'))['s'] or 0
        prem = invoices.filter(issued_at__gte=month_start, issued_at__lt=month_end).aggregate(
            s=Sum('buyer_premium'))['s'] or 0
        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'revenue': float(rev),
            'premium': float(prem),
        })

    # ── Bidding Activity ─────────────────────────────────
    total_bids   = Bid.objects.count()
    total_lots   = Lot.objects.count()
    avg_bids_lot = round(total_bids / total_lots, 1) if total_lots else 0

    top_bidders = (
        Bid.objects.values('user__username')
        .annotate(bid_count=Count('id'), total_spent=Sum('amount'))
        .order_by('-bid_count')[:5]
    )

    # ── Item Status ──────────────────────────────────────
    item_status_data = {}
    for key, label in Item.STATUS_CHOICES:
        item_status_data[label] = Item.objects.filter(status=key).count()

    # ── Live Counts ──────────────────────────────────────
    live_auctions = Auction.objects.filter(status='live').count()
    active_lots   = Lot.objects.filter(status='active').count()
    total_users_with_deposit = SecurityDeposit.objects.filter(status='active').count()

    context = {
        'total_wallet':              float(total_wallet),
        'total_bid_revenue':         float(total_bid_revenue),
        'total_premium_rev':         float(total_premium_rev),
        'total_shipping_rev':        float(total_shipping_rev),
        'auction_status_json':       json.dumps(auction_status_data),
        'lot_status_json':           json.dumps(lot_status_data),
        'item_status_json':          json.dumps(item_status_data),
        'monthly_data_json':         json.dumps(monthly_data),
        'top_auctions':              top_auctions,
        'top_bidders':               top_bidders,
        'total_bids':                total_bids,
        'avg_bids_lot':              avg_bids_lot,
        'live_auctions':             live_auctions,
        'active_lots':               active_lots,
        'total_users_with_deposit':  total_users_with_deposit,
    }
    return render(request, 'admin_panel/analytics.html', context)


@staff_member_required
def auction_analytics_detail(request, auction_id):
    """Per-auction detailed analytics."""
    auction = get_object_or_404(Auction, id=auction_id)
    lots = auction.lots.prefetch_related('bids', 'items').select_related('winning_bidder', 'invoice').order_by('lot_number')

    total_lots     = lots.count()
    sold_lots      = lots.filter(status='sold').count()
    unsold_lots    = lots.filter(status='unsold').count()
    active_lots    = lots.filter(status='active').count()

    # Revenue stats
    total_bid_revenue  = lots.filter(invoice__isnull=False).aggregate(s=Sum('invoice__amount'))['s']  or Decimal('0')
    total_premium_rev  = lots.filter(invoice__isnull=False).aggregate(s=Sum('invoice__buyer_premium'))['s'] or Decimal('0')
    total_shipping_rev = lots.filter(invoice__isnull=False).aggregate(s=Sum('invoice__shipping_fee'))['s'] or Decimal('0')
    total_revenue      = total_bid_revenue + total_premium_rev + total_shipping_rev

    # Bidding stats
    total_bids    = Bid.objects.filter(lot__auction=auction).count()
    unique_bidders = Bid.objects.filter(lot__auction=auction).values('user').distinct().count()
    avg_bids_lot  = round(total_bids / total_lots, 1) if total_lots else 0

    # Per-lot breakdown
    lot_breakdown = []
    for lot in lots:
        bid_count    = lot.bids.count()
        winning_bid  = lot.current_bid if lot.status != 'unsold' else Decimal('0')
        try:
            invoice   = lot.invoice
            premium   = invoice.buyer_premium
            total_paid = invoice.amount + invoice.shipping_fee + invoice.buyer_premium
        except Exception:
            invoice  = None
            premium  = Decimal('0')
            total_paid = Decimal('0')

        lot_breakdown.append({
            'lot': lot,
            'bid_count':   bid_count,
            'winning_bid': winning_bid,
            'premium':     premium,
            'total_paid':  total_paid,
            'winner':      lot.winning_bidder.username if lot.winning_bidder else '—',
        })

    context = {
        'auction':          auction,
        'total_lots':       total_lots,
        'sold_lots':        sold_lots,
        'unsold_lots':      unsold_lots,
        'active_lots':      active_lots,
        'total_bid_revenue':  float(total_bid_revenue),
        'total_premium_rev':  float(total_premium_rev),
        'total_shipping_rev': float(total_shipping_rev),
        'total_revenue':      float(total_revenue),
        'total_bids':         total_bids,
        'unique_bidders':     unique_bidders,
        'avg_bids_lot':       avg_bids_lot,
        'lot_breakdown':      lot_breakdown,
    }
    return render(request, 'admin_panel/auction_analytics_detail.html', context)
