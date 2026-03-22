from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.http import JsonResponse
import json

@staff_member_required
def admin_users(request):
    """List all users for admin management."""
    q         = request.GET.get('q', '').strip()
    is_active = request.GET.get('is_active', '')
    role      = request.GET.get('role', '')

    users = User.objects.all().order_by('-date_joined')

    if q:
        from django.db.models import Q
        users = users.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    if is_active == 'true':
        users = users.filter(is_active=True)
    elif is_active == 'false':
        users = users.filter(is_active=False)

    if role == 'staff':
        users = users.filter(is_staff=True)
    elif role == 'user':
        users = users.filter(is_staff=False, is_superuser=False)

    return render(request, 'admin_panel/users.html', {
        'users': users,
        'q': q,
        'is_active': is_active,
        'role': role,
    })

@staff_member_required
def toggle_user_status(request, user_id):
    """
    Suspend or activate a user via AJAX.
    If suspended, instantly invalidate their active sessions and notify via WebSocket.
    """
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        
        # Don't let admins suspend themselves
        if user == request.user:
            return JsonResponse({'success': False, 'error': 'You cannot suspend your own account.'})
            
        data = json.loads(request.body)
        is_active = data.get('is_active', True)
        
        user.is_active = is_active
        user.save()
        
        # Broadcast to specific user to force UI redirect if connected
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        
        # Notify the suspended user
        async_to_sync(channel_layer.group_send)(
            f'user_updates_{user.id}',
            {
                'type': 'user_status_update',
                'is_active': is_active
            }
        )
        
        # Notify admins
        if not is_active:
            async_to_sync(channel_layer.group_send)(
                'admin_updates',
                {
                    'type': 'admin_notification',
                    'title': 'User Suspended',
                    'message': f'{user.username} has been suspended.',
                    'level': 'warning'
                }
            )
            
        return JsonResponse({'success': True, 'is_active': user.is_active})
        
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
