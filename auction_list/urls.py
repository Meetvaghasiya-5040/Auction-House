from django.urls import path, include
from . import views, views_delivery


urlpatterns = [

    path("auctions/", views.auctions_list, name="auctions"),
    path("auction/<slug:slug>/", views.auction_detail, name="auction_detail"),
    path("all_auction/", views.auctions_list, name="all_auction"),
    path("admin/get-items-by-category/", views.get_items_by_category),
    path("lots/", views.view_lots, name="view_lots"),
    path("lots/auction/<slug:slug>/", views.view_lots, name="view_lots"),
    path("lot/<slug:slug>/", views.lot_detail, name="lot_detail"),
    path(
        "auction/<slug:slug>/register/",
        views.auction_register,
        name="auction_register",
    ),
    path(
        "auction/<slug:slug>/unregister/",
        views.auction_unregister,
        name="auction_unregister",
    ),
    path("lot/<slug:slug>/place-bid/", views.place_bid, name="place_bid"),
    path("lot/<slug:slug>/chat/", views.send_chat_message, name="send_chat_message"),
    path("lot/<slug:slug>/updates/", views.get_lot_updates, name="get_lot_updates"),
    path("updates/", views.get_auction_updates, name="get_auction_updates"),
    
    # Delivery System
    path("admin/delivery/", views_delivery.delivery_dashboard, name="delivery_dashboard"),
    path("admin/delivery/history/", views_delivery.delivery_history, name="delivery_history"),
    path("admin/delivery/pickup/verify/<int:item_id>/", views_delivery.verify_pickup_otp, name="verify_pickup_otp"),
    path("admin/delivery/pickup/mark-warehouse/<int:item_id>/", views_delivery.admin_mark_at_warehouse, name="admin_mark_at_warehouse"),
    path("admin/delivery/verify/<int:lot_id>/", views_delivery.verify_delivery_otp, name="verify_delivery_otp"),
    path("delivery/track/<int:lot_id>/", views_delivery.user_delivery_tracking, name="user_delivery_tracking"),
]

