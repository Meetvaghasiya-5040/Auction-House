
from django.contrib import admin
from django.urls import path, include
from AuctionHouse import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("otp-form/", views.otp_form, name="otp_form"),
    path("change-password/", views.change_password_view, name="change_password"),
    path("home/", include("Home.urls")),
    path("auctions/", include("auction_list.urls")),
    path("bids/", include("bids.urls")),
    ]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
