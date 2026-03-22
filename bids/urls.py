from django.urls import path
from . import views
from . import invoice_generator

urlpatterns = [
    path('deposit/create/', views.create_deposit_order, name='create_deposit_order'),
    path('deposit/verify/', views.verify_deposit, name='verify_deposit'),
    path('deposit/status/', views.security_deposit_status, name='security_deposit_status'),
    path('deposit/withdraw/', views.withdraw_deposit, name='withdraw_deposit'),
    path('my-bids/', views.my_bids, name='my_bids'),
    path('won-lots/', views.won_lots, name='won_lots'),
    path('place-bid/<slug:slug>/', views.place_bid_api, name='place_bid_api'),
    path('lot/<slug:slug>/updates/', views.get_bid_updates, name='get_bid_updates'),
    path('download-invoice/', invoice_generator.download_bid_history_pdf, name='download_invoice'),
    path('download-invoice/<int:invoice_id>/', invoice_generator.download_invoice_by_id, name='download_invoice-1'),
    path('my-invoices/', views.my_invoices, name='my_invoices'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('verify-payment-pin/', views.verify_payment_pin, name='verify_payment_pin'),
    path('lot/<slug:slug>/payment-modal/', views.payment_modal_fragment, name='payment_modal_fragment'),

    path('lot/<int:lot_id>/mark-at-warehouse/', views.mark_at_warehouse, name='mark_at_warehouse'),
    path('lot/<int:lot_id>/mark-shipped-to-buyer/', views.mark_shipped_to_buyer, name='mark_shipped_to_buyer'),
    path('lot/<int:lot_id>/confirm-delivery/', views.confirm_delivery, name='confirm_delivery'),
    path('verify-delivery-otp/', views.verify_delivery_otp, name='verify_delivery_otp'),
    path('proxy/set/<slug:lot_slug>/', views.set_proxy_bid, name='set_proxy_bid'),
    path('proxy/cancel/<slug:lot_slug>/', views.cancel_proxy_bid, name='cancel_proxy_bid'),
    path('proxy/status/<slug:lot_slug>/', views.get_proxy_bid_status, name='get_proxy_bid_status'),
    path('wallet/add-bank/', views.add_bank_account, name='add_bank_account'),
    path('wallet/withdraw/', views.request_withdrawal, name='request_withdrawal'),
]

