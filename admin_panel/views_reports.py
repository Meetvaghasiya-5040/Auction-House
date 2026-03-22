import csv
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal

from auction_list.models import Auction, Lot, Item, Invoice, Delivery
from bids.models import Bid, SecurityDeposit


@staff_member_required
def reports_home(request):
    """Landing page listing all available reports."""
    return render(request, 'admin_panel/reports_home.html')


# ─── Helper ──────────────────────────────────────────────────────────────────
def _csv_response(filename):
    """Return an HttpResponse configured for CSV download."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # BOM for Excel compatibility
    return response


# ─── Auctions Report ─────────────────────────────────────────────────────────
@staff_member_required
def report_auctions(request):
    status_filter = request.GET.get('status', '')
    date_from     = request.GET.get('date_from', '')
    date_to       = request.GET.get('date_to', '')

    qs = Auction.objects.annotate(
        lot_count  = Count('lots'),
        sold_count = Count('lots', filter=Q(lots__status='sold')),
        total_rev  = Sum('lots__invoice__amount'),
        total_prem = Sum('lots__invoice__buyer_premium'),
    ).order_by('-created_at')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    if request.GET.get('export') == 'csv':
        response = _csv_response(f'auctions_report_{timezone.now().strftime("%Y%m%d")}.csv')
        writer = csv.writer(response)
        writer.writerow(['ID', 'Title', 'Status', 'Type', 'Start Date', 'End Date',
                         'Lots', 'Sold Lots', 'Total Revenue (₹)', 'Buyer Premium (₹)', 'Created At'])
        for a in qs:
            writer.writerow([
                a.id, a.title, a.get_status_display(), a.get_auction_type_display(),
                a.start_date.strftime('%Y-%m-%d') if a.start_date else '',
                a.end_date.strftime('%Y-%m-%d') if a.end_date else '',
                a.lot_count, a.sold_count,
                float(a.total_rev or 0), float(a.total_prem or 0),
                a.created_at.strftime('%Y-%m-%d'),
            ])
        return response

    context = {
        'auctions': qs,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'status_choices': Auction.STATUS_CHOICES,
    }
    return render(request, 'admin_panel/report_auctions.html', context)


# ─── Bids Report ─────────────────────────────────────────────────────────────
@staff_member_required
def report_bids(request):
    auction_id = request.GET.get('auction_id', '')
    date_from  = request.GET.get('date_from', '')
    date_to    = request.GET.get('date_to', '')

    qs = Bid.objects.select_related('user', 'lot', 'lot__auction').order_by('-timestamp')

    if auction_id:
        qs = qs.filter(lot__auction_id=auction_id)
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)

    if request.GET.get('export') == 'csv':
        response = _csv_response(f'bids_report_{timezone.now().strftime("%Y%m%d")}.csv')
        writer = csv.writer(response)
        writer.writerow(['Bid ID', 'Bidder', 'Lot', 'Auction', 'Amount (₹)', 'Is Auto Bid', 'Is Winning', 'Timestamp'])
        for b in qs:
            writer.writerow([
                b.id, b.user.username, b.lot.title, b.lot.auction.title,
                float(b.amount), 'Yes' if b.is_auto_bid else 'No',
                'Yes' if b.is_winning else 'No',
                b.timestamp.strftime('%Y-%m-%d %H:%M'),
            ])
        return response

    total_bids     = qs.count()
    total_amount   = qs.aggregate(s=Sum('amount'))['s'] or 0
    auto_bids      = qs.filter(is_auto_bid=True).count()

    context = {
        'bids': qs[:200],
        'total_bids': total_bids,
        'total_amount': float(total_amount),
        'auto_bids': auto_bids,
        'auction_id': auction_id,
        'date_from': date_from,
        'date_to': date_to,
        'auctions': Auction.objects.all().order_by('title'),
    }
    return render(request, 'admin_panel/report_bids.html', context)


# ─── Revenue Report ───────────────────────────────────────────────────────────
@staff_member_required
def report_revenue(request):
    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')

    qs = Invoice.objects.filter(status='paid').select_related('user', 'lot', 'lot__auction').order_by('-issued_at')

    if date_from:
        qs = qs.filter(issued_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(issued_at__date__lte=date_to)

    agg = qs.aggregate(
        total_bid=Sum('amount'),
        total_premium=Sum('buyer_premium'),
        total_shipping=Sum('shipping_fee'),
    )
    total_bid      = agg['total_bid'] or Decimal('0')
    total_premium  = agg['total_premium'] or Decimal('0')
    total_shipping = agg['total_shipping'] or Decimal('0')
    grand_total    = total_bid + total_premium + total_shipping

    if request.GET.get('export') == 'csv':
        response = _csv_response(f'revenue_report_{timezone.now().strftime("%Y%m%d")}.csv')
        writer = csv.writer(response)
        writer.writerow(['Invoice #', 'Buyer', 'Lot', 'Auction', 'Bid Amount (₹)',
                         'Buyer Premium (₹)', 'Shipping (₹)', 'Total (₹)', 'Date'])
        for inv in qs:
            total = (inv.amount or 0) + (inv.buyer_premium or 0) + (inv.shipping_fee or 0)
            writer.writerow([
                inv.invoice_number, inv.user.username,
                inv.lot.title, inv.lot.auction.title,
                float(inv.amount), float(inv.buyer_premium),
                float(inv.shipping_fee), float(total),
                inv.issued_at.strftime('%Y-%m-%d'),
            ])
        return response

    context = {
        'invoices': qs,
        'total_bid':      float(total_bid),
        'total_premium':  float(total_premium),
        'total_shipping': float(total_shipping),
        'grand_total':    float(grand_total),
        'date_from': date_from,
        'date_to':   date_to,
    }
    return render(request, 'admin_panel/report_revenue.html', context)


# ─── Delivery Report ─────────────────────────────────────────────────────────
@staff_member_required
def report_delivery(request):
    status_filter = request.GET.get('status', '')
    date_from     = request.GET.get('date_from', '')
    date_to       = request.GET.get('date_to', '')

    qs = Lot.objects.filter(
        status__in=['paid', 'shipped_to_warehouse', 'at_warehouse', 'shipped', 'sold']
    ).select_related('winning_bidder', 'delivery', 'auction').order_by('-updated_at')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(updated_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(updated_at__date__lte=date_to)

    if request.GET.get('export') == 'csv':
        response = _csv_response(f'delivery_report_{timezone.now().strftime("%Y%m%d")}.csv')
        writer = csv.writer(response)
        writer.writerow(['Lot #', 'Title', 'Auction', 'Winner', 'Lot Status',
                         'Delivery Status', 'Tracking #', 'Shipping Fee (₹)', 'Updated'])
        for lot in qs:
            delivery = getattr(lot, 'delivery', None)
            writer.writerow([
                lot.lot_number, lot.title, lot.auction.title,
                lot.winning_bidder.username if lot.winning_bidder else '—',
                lot.get_status_display(),
                delivery.get_status_display() if delivery else '—',
                delivery.tracking_number if delivery else '—',
                float(lot.shipping_fee),
                lot.updated_at.strftime('%Y-%m-%d'),
            ])
        return response

    delivery_statuses = [
        ('paid', 'Paid — Awaiting Shipment'),
        ('shipped_to_warehouse', 'Shipped to Warehouse'),
        ('at_warehouse', 'At Warehouse'),
        ('shipped', 'Shipped to Buyer'),
        ('sold', 'Delivered'),
    ]

    context = {
        'lots': qs,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to':   date_to,
        'delivery_statuses': delivery_statuses,
    }
    return render(request, 'admin_panel/report_delivery.html', context)
