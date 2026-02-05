from django.contrib import admin
from .models import Wallet, Bid, Transaction,AdminWallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Balance', {
            'fields': ('balance',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ['user', 'lot', 'amount', 'timestamp', 'is_winning', 'is_auto_bid']
    list_filter = ['is_winning', 'is_auto_bid', 'timestamp']
    search_fields = ['user__username', 'lot__title']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    
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
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'transaction_type', 'amount', 'timestamp', 'description']
    list_filter = ['transaction_type', 'timestamp']
    search_fields = ['wallet__user__username', 'description']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('wallet', 'transaction_type', 'amount', 'description')
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
class AdminWallet(admin.ModelAdmin):
    list_display = ['balance']