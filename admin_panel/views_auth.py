import json
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib import messages

def admin_login_view(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('admin_panel:dashboard')

    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        if not username_or_email or not password:
            messages.error(request, "Please enter both username/email and password.")
            return render(request, 'admin_panel/login.html')

        user = None
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if "@" in username_or_email:
            try:
                user_obj = User.objects.get(email=username_or_email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None
        else:
            user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            if user.is_active and user.is_superuser:
                auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, f"Welcome to Custom Admin, {user.username}!")
                return redirect('admin_panel:dashboard')
            else:
                messages.error(request, "Unauthorized access. Only superusers are permitted.")
                return render(request, 'admin_panel/login.html')
        else:
            messages.error(request, "Invalid username/email or password.")
            return render(request, 'admin_panel/login.html')

    return render(request, 'admin_panel/login.html')
