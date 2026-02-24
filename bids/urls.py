from django.urls import path
from . import views
from . import invoice_generator

urlpatterns = [
    path('wallet/', views.wallet_dashboard, name='wallet_dashboard'),
    path('wallet/add-funds/', views.add_funds, name='add_funds'),
    path('my-bids/', views.my_bids, name='my_bids'),
    path('won-lots/', views.won_lots, name='won_lots'),
    path('place-bid/<slug:slug>/', views.place_bid_api, name='place_bid_api'),
    path('lot/<slug:slug>/updates/', views.get_bid_updates, name='get_bid_updates'),
    path('download-invoice/', invoice_generator.download_bid_history_pdf, name='download_invoice'),
    path('download-transaction-invoice/', invoice_generator.transaction_invoice, name='transaction_invoice'),
    path('download-invoice/<int:invoice_id>/', invoice_generator.download_invoice_by_id, name='download_invoice-1'),
    path('my-invoices/', views.my_invoices, name='my_invoices'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('verify-payment-pin/', views.verify_payment_pin, name='verify_payment_pin'),
    path('lot/<slug:slug>/payment-modal/', views.payment_modal_fragment, name='payment_modal_fragment'),
    path('lot/<int:lot_id>/mark-shipped-to-warehouse/', views.mark_shipped_to_warehouse, name='mark_shipped_to_warehouse'),
    path('lot/<int:lot_id>/mark-at-warehouse/', views.mark_at_warehouse, name='mark_at_warehouse'),
    path('lot/<int:lot_id>/mark-shipped-to-buyer/', views.mark_shipped_to_buyer, name='mark_shipped_to_buyer'),
    path('lot/<int:lot_id>/confirm-delivery/', views.confirm_delivery, name='confirm_delivery'),
    path('verify-delivery-otp/', views.verify_delivery_otp, name='verify_delivery_otp'),
    path('wallet/withdraw/', views.withdraw_funds, name='withdraw_funds'),
]

