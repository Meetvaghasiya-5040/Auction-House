from django.urls import path
from . import views
from . import views_users
from . import views_finance
from . import views_items
from . import views_auctions
from . import views_moderation
from . import views_delivery
from . import views_analytics
from . import views_reports
from . import views_notifications
from . import views_auth
from . import views_property_sale
from . import views_search

app_name = 'admin_panel'

urlpatterns = [
    path('login/', views_auth.admin_login_view, name='login'),
    path('search/', views_search.admin_global_search, name='global_search'),
    path('', views.admin_dashboard, name='dashboard'),
    path('users/', views_users.admin_users, name='users'),
    path('users/<int:user_id>/toggle/', views_users.toggle_user_status, name='toggle_user_status'),
    path('finance/', views_finance.admin_finance, name='finance'),
    path('finance/report/', views_finance.admin_finance_report, name='finance_report'),
    path('finance/invoice/<int:invoice_id>/download/', views_finance.admin_download_invoice, name='download_invoice'),
    path('finance/payment/<int:payment_id>/force/', views_finance.admin_force_payment, name='force_payment'),
    path('items/', views_items.admin_items, name='items'),
    path('items/<slug:item_slug>/', views_items.admin_item_detail, name='item_detail'),
    path('items/<int:item_id>/status/', views_items.update_item_status, name='update_item_status'),
    
    path('auctions/', views_auctions.admin_auctions, name='auctions'),
    path('auctions/history/', views_auctions.auction_history, name='auction_history'),
    path('auctions/create/', views_auctions.auction_create, name='auction_create'),
    path('auctions/eligible-items/', views_auctions.fetch_available_items, name='fetch_eligible_items'),
    path('auctions/<int:auction_id>/toggle/', views_auctions.toggle_auction_status, name='toggle_auction_status'),
    path('auctions/<int:auction_id>/edit/', views_auctions.auction_edit, name='auction_edit'),
    path('auctions/<int:auction_id>/delete/', views_auctions.auction_delete, name='auction_delete'),
    path('auctions/create-lot/', views_auctions.create_lot_ajax, name='create_lot_ajax'),
    
    path('moderation/', views_moderation.admin_moderation, name='moderation'),
    path('moderation/bid/<int:bid_id>/delete/', views_moderation.delete_bid_ajax, name='delete_bid'),
    
    path('delivery/', views_delivery.admin_delivery, name='delivery'),
    path('delivery/<int:delivery_id>/update/', views_delivery.update_delivery_status, name='update_delivery_status'),
    path('delivery/pickup/<int:item_id>/verify-otp/', views_delivery.admin_verify_pickup_otp, name='verify_pickup_otp'),
    path('delivery/pickup/<int:item_id>/warehouse/', views_delivery.admin_mark_at_warehouse, name='mark_at_warehouse'),
    path('delivery/lot/<int:lot_id>/verify-otp/', views_delivery.admin_verify_delivery_otp, name='verify_delivery_otp'),
    path('invoices/', views_delivery.admin_invoices, name='invoices'),

    # ── Property Sales ──────────────────────────────────────────────
    path('property-sales/', views_property_sale.admin_property_sales, name='property_sales'),
    path('property-sales/<int:sale_id>/detail/', views_property_sale.admin_property_sale_detail, name='property_sale_detail'),
    path('property-sales/<int:sale_id>/verify-docs/', views_property_sale.admin_verify_docs, name='property_sale_verify_docs'),
    path('property-sales/<int:sale_id>/generate-agreement/', views_property_sale.admin_generate_agreement, name='property_sale_generate_agreement'),
    path('property-sales/<int:sale_id>/update-registration/', views_property_sale.admin_update_registration, name='property_sale_update_registration'),
    path('property-sales/<int:sale_id>/confirm-possession/', views_property_sale.admin_confirm_possession, name='property_sale_confirm_possession'),

    # ── Analytics ────────────────────────────────────────────────────
    path('analytics/', views_analytics.admin_analytics, name='analytics'),
    path('analytics/<int:auction_id>/', views_analytics.auction_analytics_detail, name='auction_analytics_detail'),

    # ── Reports ──────────────────────────────────────────────────────
    path('reports/', views_reports.reports_home, name='reports'),
    path('reports/auctions/', views_reports.report_auctions, name='report_auctions'),
    path('reports/bids/', views_reports.report_bids, name='report_bids'),
    path('reports/revenue/', views_reports.report_revenue, name='report_revenue'),
    path('reports/delivery/', views_reports.report_delivery, name='report_delivery'),

    # Notifications
    path('notifications/', views_notifications.admin_notifications, name='notifications'),
    path('notifications/history/', views_notifications.notification_history, name='notification_history'),
    path('notifications/<int:notif_id>/read/', views_notifications.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views_notifications.mark_all_read, name='mark_all_read'),
    path('notifications/unread-count/', views_notifications.unread_count_api, name='unread_count_api'),
]
