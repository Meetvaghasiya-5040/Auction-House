from django.urls import path
from . import views
from . import invoice_generator

urlpatterns = [
    path('wallet/', views.wallet_dashboard, name='wallet_dashboard'),
    path('wallet/add-funds/', views.add_funds, name='add_funds'),
    path('my-bids/', views.my_bids, name='my_bids'),
    path('won-lots/', views.won_lots, name='won_lots'),
    path('place-bid/<int:lot_id>/', views.place_bid_api, name='place_bid_api'),
    path('lot/<int:lot_id>/updates/', views.get_bid_updates, name='get_bid_updates'),
    path('download-invoice/', invoice_generator.download_bid_history_pdf, name='download_invoice'),
    path('download-transaction-invoice/', invoice_generator.transaction_invoice, name='transaction_invoice'),
    path('my-invoices/', views.my_invoices, name='my_invoices'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
]
