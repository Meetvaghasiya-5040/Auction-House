from django.urls import path
from Home import views


urlpatterns = [
    path('', views.home_view, name='home'),
    path('logout/', views.logoutview, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('add-item/', views.add_item_view, name='add_item'),
    path('delete-item/<int:item_id>/', views.delete_item_view, name='delete_item'),
    path('edit-item/<int:item_id>/', views.edit_item_view, name='edit_item'),
    path('item-detail/<int:item_id>/<slug:slug>/',views.item_detail,name='item_detail')
]