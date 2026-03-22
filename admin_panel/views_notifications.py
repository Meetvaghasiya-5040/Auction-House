from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from .models import AdminNotification


def _split_notifications(qs):
    """Split a queryset into current (< 24h) and archived (>= 24h)."""
    cutoff = timezone.now() - timedelta(hours=24)
    current  = qs.filter(created_at__gte=cutoff)
    archived = qs.filter(created_at__lt=cutoff)
    return current, archived


@staff_member_required
def admin_notifications(request):
    """
    Show current (< 24h old) notifications. Unread shown first.
    """
    all_notifs = AdminNotification.objects.select_related('item', 'triggered_by')
    cutoff = timezone.now() - timedelta(hours=24)
    notifications = all_notifs.filter(created_at__gte=cutoff)
    unread_count  = AdminNotification.objects.filter(is_read=False).count()

    context = {
        'notifications': notifications,
        'unread_count':  unread_count,
    }
    return render(request, 'admin_panel/notifications.html', context)


@staff_member_required
def notification_history(request):
    """
    Show archived notifications (>= 24h old), grouped by date.
    Supports ?type= and ?date= filters.
    """
    cutoff = timezone.now() - timedelta(hours=24)
    qs = AdminNotification.objects.select_related('item', 'triggered_by').filter(
        created_at__lt=cutoff
    )

    type_filter = request.GET.get('type', '')
    date_filter = request.GET.get('date', '')

    if type_filter:
        qs = qs.filter(notification_type=type_filter)
    if date_filter:
        try:
            from datetime import date
            d = date.fromisoformat(date_filter)
            qs = qs.filter(created_at__date=d)
        except ValueError:
            pass

    # Group by day
    from itertools import groupby
    from django.utils.dateformat import format as df
    grouped = {}
    for notif in qs:
        day_key = notif.created_at.strftime('%Y-%m-%d')
        grouped.setdefault(day_key, []).append(notif)

    # Convert to sorted list of (date_label, [notifs])
    grouped_list = sorted(grouped.items(), reverse=True)
    grouped_display = [
        (timezone.datetime.strptime(k, '%Y-%m-%d').strftime('%A, %d %b %Y'), v)
        for k, v in grouped_list
    ]

    context = {
        'grouped_display':  grouped_display,
        'type_filter':      type_filter,
        'date_filter':      date_filter,
        'type_choices':     AdminNotification.TYPE_CHOICES,
    }
    return render(request, 'admin_panel/notification_history.html', context)


@staff_member_required
def mark_notification_read(request, notif_id):
    if request.method == 'POST':
        AdminNotification.objects.filter(id=notif_id).update(is_read=True)
        count = AdminNotification.objects.filter(is_read=False).count()
        return JsonResponse({'success': True, 'unread_count': count})
    return JsonResponse({'success': False}, status=405)


@staff_member_required
def mark_all_read(request):
    if request.method == 'POST':
        AdminNotification.objects.filter(is_read=False).update(is_read=True)
        return JsonResponse({'success': True, 'unread_count': 0})
    return JsonResponse({'success': False}, status=405)


@staff_member_required
def unread_count_api(request):
    count = AdminNotification.objects.filter(is_read=False).count()
    recent = AdminNotification.objects.filter(
        is_read=False
    ).select_related('item', 'triggered_by').order_by('-created_at')[:10]
    data = {
        'count': count,
        'notifications': [
            {
                'id':                n.id,
                'title':             n.title,
                'message':           n.message,
                'level':             n.level,
                'notification_type': n.notification_type,
                'item_slug':         n.item.slug if n.item else None,
                'triggered_by':      n.triggered_by.username if n.triggered_by else '',
                'timestamp':         n.created_at.strftime('%H:%M'),
                'time_ago':          _time_ago(n.created_at),
            }
            for n in recent
        ]
    }
    return JsonResponse(data)


def _time_ago(dt):
    diff = timezone.now() - dt
    secs = int(diff.total_seconds())
    if secs < 60:   return f'{secs}s ago'
    if secs < 3600: return f'{secs // 60}m ago'
    if secs < 86400: return f'{secs // 3600}h ago'
    return f'{secs // 86400}d ago'
