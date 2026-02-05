from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/lot/<int:lot_id>/', consumers.BiddingConsumer.as_asgi()),
    path('ws/auction/<int:auction_id>/', consumers.BiddingConsumer.as_asgi()),
]
