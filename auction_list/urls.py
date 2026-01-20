from django.urls import path,include
from . import views


urlpatterns = [
    path('',views.create_auction,name='create_auction'),
    path('all_auction/',views.auctions_list,name='all_auction'),
    path('auction-report/',views.auction_report_pdf,name='auction_report'),
    path("admin/get-items-by-category/", views.get_items_by_category),
    path('view_lots/',views.view_lots,name='view_lots'),
    path('lot-detail/<int:lot_id>/',views.lot_detail,name='lot_detail')
]