from django.urls import path, include
from . import views


urlpatterns = [

    path("auctions/", views.auctions_list, name="auctions"),
    path("auction/<int:auction_id>/", views.auction_detail, name="auction_detail"),
    path("all_auction/", views.auctions_list, name="all_auction"),
    path("admin/get-items-by-category/", views.get_items_by_category),
    path("lots/", views.view_lots, name="view_lots"),
    path("lots/auction/<int:auction_id>/", views.view_lots, name="view_lots"),
    path("lot-detail/<int:lot_id>/", views.lot_detail, name="lot_detail"),
    path(
        "auction_register/<int:auction_id>/",
        views.auction_register,
        name="auction_register",
    ),
    path(
        "auction_unregister/<int:auction_id>/",
        views.auction_unregister,
        name="auction_unregister",
    ),
    path("lot/<int:lot_id>/place-bid/", views.place_bid, name="place_bid"),
    path("lot/<int:lot_id>/chat/", views.send_chat_message, name="send_chat_message"),
    path("lot/<int:lot_id>/updates/", views.get_lot_updates, name="get_lot_updates"),
    path("updates/", views.get_auction_updates, name="get_auction_updates"),
]
