from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/admin_updates/', consumers.AdminConsumer.as_asgi()),
]
