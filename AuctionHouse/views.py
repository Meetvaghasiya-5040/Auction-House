from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import login, authenticate
from django.contrib.auth.hashers import make_password
from Home.models import Profile
from PIL import Image
from django.conf import settings
from random import randint
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from auction_list.models import Auction,Item
from django.contrib.auth import get_user_model
import threading


def is_valid_email(email):
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    try:
        validate_email(email)
        return True
    except ValidationError:
        return False

def suspended_view(request):
    return render(request, "suspended.html")


def login_view(request):
    User = get_user_model()

    if request.method == "POST":
        username_or_email = request.POST.get("username")
        password = request.POST.get("password")

        if not username_or_email or not password:
            messages.error(request, "Please enter both username/email and password.")
            return render(request, "login.html")

        user = None

        if "@" in username_or_email:
            try:
                user_obj = User.objects.get(email=username_or_email)
                user = authenticate(
                    request, username=user_obj.username, password=password
                )
            except User.DoesNotExist:
                user = None
        else:
            user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            if user.is_active:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                
                # Handle Remember Me
                remember_me = request.POST.get("remember_me")
                if remember_me == "true":
                    # Set session expiry to 30 days
                    request.session.set_expiry(30 * 24 * 60 * 60)
                else:
                    # Session expires on browser close
                    request.session.set_expiry(0)

                messages.success(request, f"Welcome back, {user.username}! 🎉")

                next_url = request.GET.get("next", "home")
                return redirect(next_url)
            else:
                messages.warning(
                    request, "Your account has been disabled. Please contact support."
                )
                return render(request, "login.html")
        else:
            messages.error(
                request, "Invalid username/email or password. Please try again."
            )
            return render(request, "login.html")
    data ={
            "count":User.objects.count(),
            "auctions":Auction.objects.all(),
            "sold_item":Item.objects.filter(status="sold").count()
        }
    return render(request, "login.html",data)


def register_view(request):
    if request.method == "POST":
        fullname = request.POST.get("fullname", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")
        profile_image = request.FILES.get("profile_image")
        terms = request.POST.get("terms")

        if not all([fullname, username, email, password, confirm_password]):
            messages.error(request, "All fields are required.")
            return render(request, "register.html")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "register.html")

        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, "register.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Please choose another one.")
            return render(request, "register.html")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered. Please use another email.")
            return render(request, "register.html")

        if not terms:
            messages.error(request, "You must accept the terms and conditions.")
            return render(request, "register.html")

        # Encode image to base64 if it exists to store in session
        profile_image_base64 = None
        profile_image_mime = None
        if profile_image:
            if profile_image.size > 5 * 1024 * 1024:
                messages.error(request, "Image file size must be less than 5MB.")
                return render(request, "register.html")
            import base64 as b64
            image_data = profile_image.read()
            profile_image_base64 = b64.b64encode(image_data).decode('utf-8')
            profile_image_mime = profile_image.content_type

        # Store data in session
        reg_data = {
            'fullname': fullname,
            'username': username,
            'email': email,
            'password': make_password(password),
            'profile_image_base64': profile_image_base64,
            'profile_image_mime': profile_image_mime,
        }
        request.session['reg_data'] = reg_data
        
        # Generate and Send OTP
        otp = randint(100000, 999999)
        request.session['reg_otp'] = str(otp)
        request.session['reg_otp_created_at'] = timezone.now().isoformat()
        
        try:
            send_mail(
                "Verify Your Email - Auction House",
                f"Your registration OTP is {otp}. This code will expire in 2 minutes.",
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            messages.info(request, f"A 6-digit OTP has been sent to {email}. Please verify to complete registration.")
            return redirect("register_otp_view")
        except Exception as e:
            messages.error(request, f"Failed to send verification email: {str(e)}")
            return render(request, "register.html")

    data = {
        "count": User.objects.count(),
        "auctions": Auction.objects.all(),
        "sold_item": Item.objects.filter(status="sold").count()
    }
    return render(request, "register.html", data)


def register_otp_view(request):
    reg_data = request.session.get('reg_data')
    if not reg_data:
        messages.error(request, "Registration session expired. Please register again.")
        return redirect("register")

    if request.method == "POST":
        user_otp = request.POST.get("otp", "").strip()
        stored_otp = request.session.get("reg_otp")
        otp_at = request.session.get("reg_otp_created_at")

        if not stored_otp or not otp_at:
            messages.error(request, "OTP session expired. Please request a new one.")
            return render(request, "register_otp.html", {"email": reg_data['email']})

        otp_time = timezone.datetime.fromisoformat(otp_at)
        if timezone.now() - otp_time > timedelta(minutes=2):
            messages.error(request, "OTP has expired. Please resend code.")
            return render(request, "register_otp.html", {"email": reg_data['email']})

        if user_otp == stored_otp:
            try:
                name_parts = reg_data['fullname'].split(" ", 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else ""

                user = User.objects.create(
                    username=reg_data['username'],
                    email=reg_data['email'],
                    first_name=first_name,
                    last_name=last_name,
                    password=reg_data['password'],
                )

                if reg_data['profile_image_base64']:
                    profile = Profile.objects.get(user=user)
                    profile.profile_image_base64 = f"data:{reg_data['profile_image_mime']};base64,{reg_data['profile_image_base64']}"
                    profile.save()

                # Cleanup session
                request.session.pop('reg_data', None)
                request.session.pop('reg_otp', None)
                request.session.pop('reg_otp_created_at', None)

                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, f"Welcome to Auction House, {first_name}! Your account has been verified and created. 🎉")
                return redirect("home")
            except Exception as e:
                messages.error(request, f"Registration failed during finalization: {str(e)}")
                return redirect("register")
        else:
            messages.error(request, "Invalid OTP. Please try again.")

    return render(request, "register_otp.html", {"email": reg_data['email']})


def resend_registration_otp(request):
    reg_data = request.session.get('reg_data')
    if not reg_data:
        return JsonResponse({'success': False, 'message': 'Session expired.'})

    otp = randint(100000, 999999)
    request.session['reg_otp'] = str(otp)
    request.session['reg_otp_created_at'] = timezone.now().isoformat()

    try:
        send_mail(
            "New OTP Code - Auction House",
            f"Your new registration OTP is {otp}. This code will expire in 2 minutes.",
            settings.DEFAULT_FROM_EMAIL,
            [reg_data['email']],
            fail_silently=False,
        )
        return JsonResponse({'success': True, 'message': 'New OTP sent!'})
    except Exception:
        return JsonResponse({'success': False, 'message': 'Failed to send OTP.'})


def otp_form(request):
    if request.method == "POST":
        if "email" in request.POST and "otp" not in request.POST:
            email = request.POST.get("email", "").strip()

            if not email or not is_valid_email(email):
                messages.error(request, "Please enter a valid email address.")
                return render(request, "otp.html")

            User = get_user_model()
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, "No account found with this email address.")
                return render(request, "otp.html")

            otp = randint(100000, 999999)

            request.session["otp"] = str(otp)
            request.session["reset_email"] = email
            request.session["otp_created_at"] = timezone.now().isoformat()

            try:
                send_mail(
                    "Your OTP Code - Auction House",
                    f"Your OTP code is {otp}. This code will expire in 2 minutes.",
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
                messages.success(request, f"Verification code sent to {email}")
            except Exception as e:
                messages.error(request, "Failed to send OTP. Please try again.")
                return render(request, "otp.html", {"email": None})

            return render(request, "otp.html", {"email": email})

        elif "otp" in request.POST:
            user_otp = request.POST.get("otp", "").strip()
            stored_otp = request.session.get("otp")
            otp_created_at = request.session.get("otp_created_at")
            email = request.session.get("reset_email")

            if not stored_otp or not otp_created_at or not email:
                messages.error(request, "Session expired. Please request a new OTP.")
                request.session.pop("otp", None)
                request.session.pop("otp_created_at", None)
                request.session.pop("reset_email", None)
                return render(request, "otp.html")

            otp_created_time = timezone.datetime.fromisoformat(otp_created_at)
            current_time = timezone.now()
            time_difference = current_time - otp_created_time

            if time_difference > timedelta(minutes=2):
                messages.error(request, "OTP has expired. Please request a new code.")
                request.session.pop("otp", None)
                request.session.pop("otp_created_at", None)
                request.session.pop("reset_email", None)
                return render(request, "otp.html")

            if user_otp == stored_otp:
                messages.success(request, "OTP verified successfully!")
                request.session["otp_verified"] = True

                request.session.pop("otp", None)
                request.session.pop("otp_created_at", None)

                return redirect("change_password")
            else:
                messages.error(request, "Invalid OTP. Please try again.")
                return render(request, "otp.html", {"email": email})

    return render(request, "otp.html")


def change_password_view(request):
    if not request.session.get("otp_verified"):
        messages.error(request, "Please verify your OTP first.")
        return redirect("otp_form")

    user_email = request.session.get("reset_email")

    if not user_email:
        messages.error(
            request, "Session expired. Please start the password reset process again."
        )
        return redirect("otp_form")

    if request.method == "POST":
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")

        if not new_password or not confirm_password:
            messages.error(request, "Please fill in all fields.")
            return render(request, "change_password.html", {"useremail": user_email})

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "change_password.html", {"useremail": user_email})

        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, "change_password.html", {"useremail": user_email})

        try:
            User = get_user_model()
            user = User.objects.get(email=user_email)
            user.set_password(new_password)
            user.save()

            request.session.pop("reset_email", None)
            request.session.pop("otp_verified", None)

            messages.success(
                request,
                "Password changed successfully! Please login with your new password.",
            )
            return redirect("login")

        except User.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect("otp_form")

    return render(
        request, "change_pass.html", {"useremail": request.session.get("reset_email")}
    )

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
import traceback

@user_passes_test(lambda u: u.is_superuser)
def test_email_config(request):
    """A test view to check SMTP configuration on Render"""
    try:
        send_mail(
            "Test Email from Auction House",
            f"If you are reading this, your email configuration is working!\n\nHost: {settings.EMAIL_HOST}\nPort: {settings.EMAIL_PORT}\nUser: {settings.EMAIL_HOST_USER}",
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email],
            fail_silently=False,
        )
        return HttpResponse(f"✅ Success! Sent test email to {request.user.email} using {settings.EMAIL_HOST_USER}")
    except Exception as e:
        error_trace = traceback.format_exc()
        return HttpResponse(f"❌ Failed to send email.\n\nError:\n{str(e)}\n\nTraceback:\n{error_trace}", content_type="text/plain")
