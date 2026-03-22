from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

class SuspendMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow static files and media to load
        if request.path.startswith('/static/') or request.path.startswith('/media/') or request.path.startswith('/custom-admin/') or request.path.startswith('/admin/'):
            return self.get_response(request)
            
        is_suspended = False
        
        if not request.user.is_authenticated:
            user_id = request.session.get('_auth_user_id')
            if user_id:
                try:
                    user = User.objects.get(pk=user_id)
                    if not user.is_active:
                        is_suspended = True
                except User.DoesNotExist:
                    pass
        else:
            if not request.user.is_active:
                is_suspended = True
                
        if is_suspended:
            allowed_paths = [reverse('suspended'), reverse('logout')]
            if request.path not in allowed_paths:
                return redirect('suspended')
                
        return self.get_response(request)
