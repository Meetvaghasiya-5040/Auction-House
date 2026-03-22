
from django.contrib import admin
from django.urls import path, include
from AuctionHouse import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("register-otp/", views.register_otp_view, name="register_otp_view"),
    path("resend-reg-otp/", views.resend_registration_otp, name="resend_registration_otp"),
    path("otp-form/", views.otp_form, name="otp_form"),
    path("change-password/", views.change_password_view, name="change_password"),
    path("home/", include("Home.urls")),
    path("auctions/", include("auction_list.urls")),
    path("bids/", include("bids.urls")),
    path("accounts/", include("allauth.urls")),
    path("custom-admin/", include("admin_panel.urls")),
    path("suspended/", views.suspended_view, name="suspended"),
]


# Always serve media files (needed even in production for user-uploaded content)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
