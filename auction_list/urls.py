from django.urls import path, include
from . import views, views_delivery, views_verification, views_property_sale


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
    
    # Document Verification System
    path("verification/", views_verification.verification_dashboard, name="verification_dashboard"),
    path("admin/verification/approve/<int:item_id>/", views_verification.approve_item, name="admin_approve_item"),
    path("admin/verification/reject/<int:item_id>/", views_verification.reject_item, name="admin_reject_item"),
    path("admin/verification/api/pending-items/", views.fetch_new_pending_items, name="api_pending_items"),
    
    # Property Sale System (Real Estate)
    path("auctions/property-sale/<int:lot_id>/", views_property_sale.property_sale_dashboard, name="property_sale_dashboard"),
    path("auctions/property-sale/<int:lot_id>/submit-documents/", views_property_sale.submit_documents, name="property_sale_submit_docs"),
    path("auctions/property-sale/verify-documents/<int:sale_id>/", views_property_sale.admin_verify_documents, name="property_sale_verify_docs"),
    path("auctions/property-sale/generate-agreement/<int:sale_id>/", views_property_sale.generate_agreement, name="property_sale_generate_agreement"),
    path("auctions/property-sale/sign-agreement/<int:sale_id>/", views_property_sale.sign_agreement, name="property_sale_sign_agreement"),
    path("auctions/property-sale/initiate-final-payment/<int:sale_id>/", views_property_sale.initiate_final_payment, name="property_sale_initiate_final_payment"),
    path("auctions/property-sale/verify-final-payment/<int:sale_id>/", views_property_sale.verify_final_payment, name="property_sale_verify_final_payment"),
    path("auctions/property-sale/update-registration/<int:sale_id>/", views_property_sale.update_registration, name="property_sale_update_registration"),
    path("auctions/property-sale/confirm-possession/<int:sale_id>/", views_property_sale.confirm_possession, name="property_sale_confirm_possession"),
    path("admin/property-sales/", views_property_sale.admin_property_sales, name="admin_property_sales"),
]

