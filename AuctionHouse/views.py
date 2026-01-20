from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.hashers import make_password
from Home.models import Profile
from PIL import Image
from random import randint
import os
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

def is_valid_email(email):
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    try:
        validate_email(email)
        return True
    except ValidationError:
        return False

def login_view(request):
    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username_or_email or not password:
            messages.error(request, 'Please enter both username/email and password.')
            return render(request, 'login.html')
        
        user = None
        
        if '@' in username_or_email:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user_obj = User.objects.get(email=username_or_email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None
        else:
            user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            if user.is_active:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}! 🎉')
                
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
            else:
                messages.warning(request, 'Your account has been disabled. Please contact support.')
                return render(request, 'login.html')
        else:
            messages.error(request, 'Invalid username/email or password. Please try again.')
            return render(request, 'login.html')
    
    return render(request, 'login.html')




def register_view(request):
    if request.method == 'POST':
        fullname = request.POST.get('fullname', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        profile_image = request.FILES.get('profile_image')
        terms = request.POST.get('terms')
        
        errors = []
        
        if not all([fullname, username, email, password, confirm_password]):
            messages.error(request, 'All fields are required.')
            return render(request, 'register.html')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html')
        
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'register.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists. Please choose another one.')
            return render(request, 'register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered. Please use another email.')
            return render(request, 'register.html')
        
        if not terms:
            messages.error(request, 'You must accept the terms and conditions.')
            return render(request, 'register.html')
        
        if profile_image:
            if profile_image.size > 5 * 1024 * 1024:
                messages.error(request, 'Image file size must be less than 5MB.')
                return render(request, 'register.html')
            
            allowed_extensions = ['jpg', 'jpeg', 'png', 'gif']
            file_extension = profile_image.name.split('.')[-1].lower()
            if file_extension not in allowed_extensions:
                messages.error(request, 'Only JPG, JPEG, PNG, and GIF images are allowed.')
                return render(request, 'register.html')
        
        try:
            name_parts = fullname.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=make_password(password)
            )
            
            if profile_image:
                profile, created = Profile.objects.get_or_create(user=user)
                profile.profile_image = profile_image
                profile.save()
                
                img_path = profile.profile_image.path
                img = Image.open(img_path)
                
                max_size = (500, 500)
                if img.height > max_size[1] or img.width > max_size[0]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    img.save(img_path, quality=90, optimize=True)
            
            login(request, user)
            
            messages.success(request, f'Welcome to Auction House, {first_name}! Your account has been created successfully. 🎉')
            return redirect('home')
            
        except Exception as e:
            messages.error(request, f'An error occurred during registration: {str(e)}')
            return render(request, 'register.html')
    
    return render(request, 'register.html')

def otp_form(request):
    if request.method == 'POST':
        if 'email' in request.POST and 'otp' not in request.POST:
            email = request.POST.get('email', '').strip()
            
            if not email or not is_valid_email(email):
                messages.error(request, 'Please enter a valid email address.')
                return render(request, 'otp.html')
            
            User = get_user_model()
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, 'No account found with this email address.')
                return render(request, 'otp.html')
            
            otp = randint(100000, 999999)
            
            request.session['otp'] = str(otp)
            request.session['reset_email'] = email
            request.session['otp_created_at'] = timezone.now().isoformat()
            
            try:
                send_mail(
                    'Your OTP Code - Auction House',
                    f'Your OTP code is {otp}. This code will expire in 2 minutes.',
                    'meetvaghasiya166@gmail.com',
                    [email],
                    fail_silently=False,
                )
                messages.success(request, f'Verification code sent to {email}')
            except Exception as e:
                messages.error(request, 'Failed to send OTP. Please try again.')
                return render(request, 'otp.html', {'email': None})
            
            return render(request, 'otp.html', {'email': email})
        
        elif 'otp' in request.POST:
            user_otp = request.POST.get('otp', '').strip()
            stored_otp = request.session.get('otp')
            otp_created_at = request.session.get('otp_created_at')
            email = request.session.get('reset_email')
            
            if not stored_otp or not otp_created_at or not email:
                messages.error(request, 'Session expired. Please request a new OTP.')
                request.session.pop('otp', None)
                request.session.pop('otp_created_at', None)
                request.session.pop('reset_email', None)
                return render(request, 'otp.html')
            
            otp_created_time = timezone.datetime.fromisoformat(otp_created_at)
            current_time = timezone.now()
            time_difference = current_time - otp_created_time
            
            if time_difference > timedelta(minutes=2):
                messages.error(request, 'OTP has expired. Please request a new code.')
                request.session.pop('otp', None)
                request.session.pop('otp_created_at', None)
                request.session.pop('reset_email', None)
                return render(request, 'otp.html')
            
            if user_otp == stored_otp:
                messages.success(request, 'OTP verified successfully!')
                request.session['otp_verified'] = True
                
                request.session.pop('otp', None)
                request.session.pop('otp_created_at', None)
                
                return redirect('change_password')
            else:
                messages.error(request, 'Invalid OTP. Please try again.')
                return render(request, 'otp.html', {'email': email})
    
    return render(request, 'otp.html')


def change_password_view(request):
    if not request.session.get('otp_verified'):
        messages.error(request, 'Please verify your OTP first.')
        return redirect('otp_form')
    
    user_email = request.session.get('reset_email')
    
    if not user_email:
        messages.error(request, 'Session expired. Please start the password reset process again.')
        return redirect('otp_form')
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not new_password or not confirm_password:
            messages.error(request, 'Please fill in all fields.')
            return render(request, 'change_password.html', {'useremail': user_email})
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'change_password.html', {'useremail': user_email})
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'change_password.html', {'useremail': user_email})
        
        try:
            User = get_user_model()
            user = User.objects.get(email=user_email)
            user.set_password(new_password)
            user.save()
            
            
            request.session.pop('reset_email', None)
            request.session.pop('otp_verified', None)
            
            messages.success(request, 'Password changed successfully! Please login with your new password.')
            return redirect('login')
            
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('otp_form')
    
    return render(request, 'change_pass.html', {'useremail' : request.session.get('reset_email')})
