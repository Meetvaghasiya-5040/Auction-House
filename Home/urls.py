from django.urls import path
from Home import views


urlpatterns = [
    path("", views.home_view, name="home"),
    path("logout/", views.logoutview, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/<str:username>/", views.profile_view, name="profile"),
    path("add-item/", views.add_item_view, name="add_item"),
    path("delete-item/<slug:slug>/", views.delete_item_view, name="delete_item"),
    path("edit-item/<slug:slug>/", views.edit_item_view, name="edit_item"),
    path(
        "item-detail/<slug:slug>/", views.item_detail, name="item_detail"
    ),
    path("edit-profile/", views.edit_profile_view, name="edit_profile"),
    path("set-transaction-pin/", views.set_transaction_pin, name="set_transaction_pin"),
    path("verify-account-password/", views.verify_account_password, name="verify_account_password"),
    path("change-transaction-pin/", views.change_transaction_pin, name="change_transaction_pin"),
    path("terms-and-condition/", views.terms_and_condition_view, name="terms_and_condition"),
    path("wallet/", views.seller_wallet, name="seller_wallet"),
]

