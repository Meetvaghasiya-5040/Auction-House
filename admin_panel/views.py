import csv
import json
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from auction_list.models import Auction, Lot, Item, Invoice
from bids.models import AdminWallet, Bid, SecurityDeposit


@staff_member_required
def admin_dashboard(request):
    """
    Main dashboard — fully dynamic, all data from the real database.
    Supports ?export=csv to download a CSV summary report.
    """
    now = timezone.now()

    # ── Top-line Metrics ─────────────────────────────────────────────
    total_users    = User.objects.count()
    admin_wallet   = AdminWallet.load()
    total_revenue  = admin_wallet.balance if admin_wallet else Decimal('0')
    live_auctions  = Auction.objects.filter(status='live').count()
    active_lots    = Lot.objects.filter(status='active').count()
    pending_items  = Item.objects.filter(status='Pending Approval').count()
    pending_auctions = Auction.objects.filter(status='pending').count()
    pending_approvals = pending_items + pending_auctions
    total_bids     = Bid.objects.count()
    total_invoices = Invoice.objects.filter(status='paid').count()
    total_bid_revenue = Invoice.objects.filter(status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_premium  = Invoice.objects.filter(status='paid').aggregate(s=Sum('buyer_premium'))['s'] or Decimal('0')
    active_deposits = SecurityDeposit.objects.filter(status='active').count()

    # ── Month-over-month deltas ───────────────────────────────────────
    month_start   = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

    users_this_month = User.objects.filter(date_joined__gte=month_start).count()
    users_prev_month = User.objects.filter(date_joined__gte=prev_month_start, date_joined__lt=month_start).count()
    bids_this_month  = Bid.objects.filter(timestamp__gte=month_start).count()
    bids_prev_month  = Bid.objects.filter(timestamp__gte=prev_month_start, timestamp__lt=month_start).count()

    def pct_change(a, b):
        if b == 0: return None
        return round((a - b) / b * 100, 1)

    users_pct  = pct_change(users_this_month, users_prev_month)
    bids_pct   = pct_change(bids_this_month, bids_prev_month)

    # ── Monthly Revenue Chart (last 6 months) ─────────────────────────
    monthly_data = []
    for i in range(5, -1, -1):
        ms = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        me = (ms + timedelta(days=32)).replace(day=1)
        rev  = Invoice.objects.filter(status='paid', issued_at__gte=ms, issued_at__lt=me).aggregate(s=Sum('amount'))['s'] or 0
        prem = Invoice.objects.filter(status='paid', issued_at__gte=ms, issued_at__lt=me).aggregate(s=Sum('buyer_premium'))['s'] or 0
        bids_m = Bid.objects.filter(timestamp__gte=ms, timestamp__lt=me).count()
        monthly_data.append({
            'month':   ms.strftime('%b %Y'),
            'revenue': float(rev),
            'premium': float(prem),
            'bids':    bids_m,
        })

    # ── Lot Status Distribution (for pie chart) ───────────────────────
    lot_status_counts = {label: Lot.objects.filter(status=key).count() for key, label in Lot.STATUS_CHOICES}

    # ── Recent Activity Feed — real events ───────────────────────────
    activity = []

    # Recent bids
    for b in Bid.objects.select_related('user', 'lot').order_by('-timestamp')[:5]:
        activity.append({
            'icon':    'fa-gavel',
            'color':   'indigo',
            'title':   f'New Bid by {b.user.username}',
            'detail':  f'₹{b.amount:,.0f} on "{b.lot.title}"',
            'time':    b.timestamp,
        })

    # Recent item submissions
    for item in Item.objects.select_related('owner').order_by('-created_at')[:3]:
        activity.append({
            'icon':    'fa-box',
            'color':   'amber',
            'title':   f'Item Submitted',
            'detail':  f'"{item.title}" by {item.owner.username} — Status: {item.status}',
            'time':    item.created_at,
        })

    # Recent user registrations
    for u in User.objects.order_by('-date_joined')[:3]:
        activity.append({
            'icon':    'fa-user-plus',
            'color':   'emerald',
            'title':   'New User Registered',
            'detail':  f'{u.username} ({u.email})',
            'time':    u.date_joined,
        })

    # Recent invoices
    for inv in Invoice.objects.select_related('user', 'lot').order_by('-issued_at')[:3]:
        activity.append({
            'icon':    'fa-file-invoice-dollar',
            'color':   'teal',
            'title':   f'Invoice Paid',
            'detail':  f'{inv.user.username} paid ₹{inv.amount:,.0f} for "{inv.lot.title}"',
            'time':    inv.issued_at,
        })

    # Sort by time descending and take top 10
    activity.sort(key=lambda x: x['time'], reverse=True)
    activity = activity[:10]

    # ── Top 5 Auctions by revenue ─────────────────────────────────────
    top_auctions = (
        Auction.objects.annotate(
            sold=Count('lots', filter=Q(lots__status='sold')),
            rev=Sum('lots__invoice__amount'),
        ).order_by('-rev')[:5]
    )

    # ── Recent lots going live/closing ───────────────────────────────
    upcoming_lots = Lot.objects.filter(status='draft').order_by('created_at')[:5]
    active_lot_list = Lot.objects.filter(status='active').select_related('auction').order_by('-end_time')[:5]

    # ── CSV Export ──────────────────────────────────────────────────
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="dashboard_report_{now.strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')  # BOM for Excel
        w = csv.writer(response)
        w.writerow(['EasyBid Admin Dashboard Report', now.strftime('%Y-%m-%d %H:%M')])
        w.writerow([])
        w.writerow(['=== PLATFORM OVERVIEW ==='])
        w.writerow(['Metric', 'Value'])
        w.writerow(['Total Users', total_users])
        w.writerow(['Total Revenue (Admin Wallet)', float(total_revenue)])
        w.writerow(['Total Bid Revenue', float(total_bid_revenue)])
        w.writerow(['Total Buyer Premium', float(total_premium)])
        w.writerow(['Live Auctions', live_auctions])
        w.writerow(['Active Lots', active_lots])
        w.writerow(['Total Bids', total_bids])
        w.writerow(['Paid Invoices', total_invoices])
        w.writerow(['Active Security Deposits', active_deposits])
        w.writerow(['Pending Approvals', pending_approvals])
        w.writerow([])
        w.writerow(['=== MONTHLY REVENUE (Last 6 Months) ==='])
        w.writerow(['Month', 'Bid Revenue', 'Buyer Premium', 'Total Bids'])
        for m in monthly_data:
            w.writerow([m['month'], m['revenue'], m['premium'], m['bids']])
        w.writerow([])
        w.writerow(['=== TOP AUCTIONS ==='])
        w.writerow(['Auction', 'Status', 'Sold Lots', 'Revenue'])
        for a in top_auctions:
            w.writerow([a.title, a.get_status_display(), a.sold or 0, float(a.rev or 0)])
        return response

    context = {
        'total_users':       total_users,
        'total_revenue':     total_revenue,
        'total_bid_revenue': total_bid_revenue,
        'total_premium':     total_premium,
        'live_auctions':     live_auctions,
        'active_lots':       active_lots,
        'pending_approvals': pending_approvals,
        'pending_items':     pending_items,
        'total_bids':        total_bids,
        'total_invoices':    total_invoices,
        'active_deposits':   active_deposits,
        'users_pct':         users_pct,
        'bids_pct':          bids_pct,
        'users_this_month':  users_this_month,
        'bids_this_month':   bids_this_month,
        'monthly_data_json': json.dumps(monthly_data),
        'lot_status_json':   json.dumps(lot_status_counts),
        'activity':          activity,
        'top_auctions':      top_auctions,
        'upcoming_lots':     upcoming_lots,
        'active_lot_list':   active_lot_list,
    }
    return render(request, 'admin_panel/dashboard.html', context)
