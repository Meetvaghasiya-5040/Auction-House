from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Bid, AdminWallet, Transaction,UserWallet


@admin.register(Bid)
class BidAdmin(ModelAdmin):
    list_filter_submit = True
    list_display = ['user', 'lot', 'amount', 'timestamp', 'is_winning', 'is_auto_bid']
    list_filter = ('user', 'lot', 'amount', 'timestamp', 'is_winning', 'is_auto_bid')
    actions = ["delete_selected"]
    search_fields = ['user__username', 'lot__title']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    list_per_page = 20    
    fieldsets = (
        ('Bid Information', {
            'fields': ('lot', 'user', 'amount')
        }),
        ('Status', {
            'fields': ('is_winning', 'is_auto_bid')
        }),
        ('Timestamp', {
            'fields': ('timestamp',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Transaction)
class TransactionAdmin(ModelAdmin):
    list_filter_submit = True
    list_display = ['user', 'transaction_type', 'amount', 'timestamp']
    search_fields = ['user__username', 'description']
    readonly_fields = ['timestamp']
    list_filter = ('transaction_type', 'amount', 'timestamp')
    actions = ["delete_selected"]
    date_hierarchy = 'timestamp'
    list_per_page = 20    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('user', 'transaction_type', 'amount', 'description')
        }),
        ('Related', {
            'fields': ('related_bid',)
        }),
        ('Timestamp', {
            'fields': ('timestamp',),
            'classes': ('collapse',)
        }),
    )

@admin.register(AdminWallet)
class AdminWalletAdmin(ModelAdmin):
    list_filter_submit = True
    list_display = ['balance']
    list_filter = ('balance',)
    actions = ["delete_selected"]
    search_fields = ['balance']
    readonly_fields = ['balance']
    list_per_page = 20

@admin.register(UserWallet)
class UserWalletAdmin(ModelAdmin):
    list_display = ['user', 'balance']