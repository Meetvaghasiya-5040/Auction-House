from django.conf import settings
from django.contrib import admin
from .models import Auction, Item, Lot, Catagory, AuctionRegister, LotRegister,Invoice
from django import forms
from django.utils.html import format_html
from django.db.models import Sum
from django.utils.safestring import mark_safe

# Register your models here.


class AuctionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status_badge",
        "auction_type",
        "start_date",
        "end_date",
        "total_lots",
        "total_value",
        "created_by",
    )
    list_filter = ("status", "auction_type", "start_date", "end_date", "created_by")
    search_fields = ("title", "description", "location")
    readonly_fields = (
        "created_at",
        "updated_at",
        "approved_at",
        "approved_by",
        "total_lots",
        "total_value",
    )

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("title", "description", "auction_type", "location")},
        ),
        (
            "Status & Approval",
            {"fields": ("status", "created_by", "approved_by", "approved_at")},
        ),
        ("Schedule", {"fields": ("start_date", "end_date")}),
        (
            "Settings",
            {
                "fields": (
                    "allow_proxy_bidding",
                    "buyer_premium_percentage",
                    "min_bid_increment",
                )
            },
        ),
        (
            "Terms & Conditions",
            {"fields": ("terms_and_conditions",), "classes": ("collapse",)},
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at", "total_lots", "total_value"),
                "classes": ("collapse",),
            },
        ),
    )

    def status_badge(self, obj):
        colors = {
            "draft": "#6b7280",
            "pending": "#f59e0b",
            "approved": "#10b981",
            "live": "#ef4444",
            "scheduled": "#8b5cf6",
            "completed": "#3b82f6",
            "cancelled": "#9ca3af",
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 500; display: inline-block;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"


admin.site.register(Auction, AuctionAdmin)


@admin.register(Catagory)
class CatagoryAdmin(admin.ModelAdmin):
    list_display = ["name", "item_count", "available_count", "created_at"]
    search_fields = ["name", "description"]
    list_per_page = 50

    def item_count(self, obj):
        count = obj.total_items
        return format_html('<span style="font-weight: bold;">{}</span>', count)

    item_count.short_description = "Total Items"

    def available_count(self, obj):
        count = obj.available_items
        return format_html(
            '<span style="color: green; font-weight: bold;">{}</span>', count
        )

    available_count.short_description = "Available"


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "item_catagory",
        "status_badge",
        "estimated_value",
        "owner",
        "current_lot_display",
        "created_at",
    ]
    list_filter = ["status", "item_catagory", "created_at"]
    search_fields = ["title", "description", "item_catagory__name"]
    readonly_fields = [
        "created_at",
        "updated_at",
        "current_lot_display",
        "preview_image",
    ]
    list_per_page = 50

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("title", "description", "item_catagory", "owner")},
        ),
        ("Valuation", {"fields": ("estimated_value",)}),
        (
            "Details",
            {"fields": ("condition", "dimensions", "weight"), "classes": ("collapse",)},
        ),
        ("Status", {"fields": ("status", "current_lot_display")}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
        ("Images", {"fields": ("preview_image",), "classes": ("collapse",)}),
    )

    # ---- PROTECT STATUS ----
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj and obj.lots.exists():
            ro.append("status")
        return ro

    def save_model(self, request, obj, form, change):
        if change:
            old = Item.objects.get(pk=obj.pk)
            if old.lots.exists():
                obj.status = old.status
        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.lots.exists():
            form.base_fields["status"].help_text = (
                "Status is controlled by Lot. Remove from lot to change."
            )
        return form

    # ---- IMAGE PREVIEW ----
    def preview_image(self, obj):
        if not obj or not obj.images:
            return "No Image"
        html = ""
        for img in obj.images:
            html += f'<img src="{settings.MEDIA_URL}{img}" width="120" style="margin:6px;border:1px solid #ccc;" />'
        return mark_safe(html)

    preview_image.short_description = "Images Preview"

    def show_images(self, obj):
        return len(obj.images) if obj.images else 0

    show_images.short_description = "Number of Images"

    # ---- STATUS BADGE ----
    def status_badge(self, obj):
        colors = {
            "available": "#535355",
            "lotted": "#f59e0b",
            "sold": "#3b82f6",
        }
        return format_html(
            '<span style="background-color:{};color:white;padding:4px 12px;'
            'border-radius:3px;font-weight:bold;font-size:11px;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            obj.get_status_display().upper(),
        )

    status_badge.short_description = "Status"

    # ---- CURRENT LOT ----
    def current_lot_display(self, obj):
        lot = obj.current_lot
        if lot:
            return format_html(
                '<a href="/admin/yourapp/lot/{}/change/" style="color:#ec4899;font-weight:bold;">Lot #{} - {}</a>',
                lot.id,
                lot.lot_number,
                lot.title,
            )
        return format_html('<span style="color:#6b7280;">{}</span>', "Not assigned")

    current_lot_display.short_description = "Current Lot"

    # ---- ACTIONS ----
    actions = ["mark_as_available", "mark_as_sold"]

    def mark_as_available(self, request, queryset):
        qs = queryset.exclude(lots__isnull=False)
        count = qs.update(status="available")
        self.message_user(request, f"{count} item(s) marked as available.")

    def mark_as_sold(self, request, queryset):
        qs = queryset.exclude(lots__isnull=False)
        count = qs.update(status="sold")
        self.message_user(request, f"{count} item(s) marked as sold.")


class LotAdminForm(forms.ModelForm):
    class Meta:
        model = Lot
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and self.instance.lot_catagory:
            self.fields["items"].queryset = Item.objects.filter(
                item_catagory=self.instance.lot_catagory, status="Available"
            )
        else:
            self.fields["items"].queryset = Item.objects.none()

        if "auction" in self.fields:
            self.fields["auction"].queryset = Auction.objects.exclude(
                status__in=["cancelled", "live", "completed"]
            )


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = (
        "lot_number",
        "title",
        "lot_catagory",
        "starting_bid",
        "auction",
        "colored_status",
        "created_at",
    )
    list_filter = ("lot_catagory", "auction", "status", "created_at")
    readonly_fields = (
        "starting_bid",
        "created_at",
        "updated_at",
        "winning_bidder",
        "current_bid",
    )
    filter_horizontal = ("items",)
    fieldsets = (
        (
            "Core Information",
            {"fields": ("auction", "lot_number", "title", "description")},
        ),
        ("Category & Items", {"fields": ("lot_catagory", "items")}),
        ("Pricing", {"fields": ("starting_bid", "reserve_price", "current_bid", "min_bid_increment")}),
        ("Status & Winner", {"fields": ("status", "winning_bidder")}),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    form = LotAdminForm

    # ---------- STATUS COLOR ----------
    def colored_status(self, obj):
        colors = {
            "draft": "#6b7280",
            "active": "#10b981",
            "sold": "#3b82f6",
            "unsold": "#f59e0b",
        }
        return format_html(
            '<span style="background:{};color:white;padding:4px 12px;border-radius:4px;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )

    colored_status.short_description = "Status"
    colored_status.admin_order_field = "status"

    # ---------- SAVE MODEL ----------
    def save_model(self, request, obj, form, change):
        if change:
            old = Lot.objects.prefetch_related("items").get(pk=obj.pk)
            obj._old_status = old.status
            obj._old_items = set(old.items.all())
        else:
            obj._old_status = None
            obj._old_items = set()
        super().save_model(request, obj, form, change)

    # ---------- SAVE RELATED ----------
    def save_related(self, request, form, formsets, change):
        lot = form.instance
        old_items = getattr(lot, "_old_items", set())
        old_status = getattr(lot, "_old_status", None)

        super().save_related(request, form, formsets, change)

        new_items = set(lot.items.all())

        if old_items != new_items or old_status != lot.status:
            self.update_item_status(lot, old_items, new_items, old_status)
            self.calculate_starting_bid(lot, old_items, new_items)

    # ---------- ITEM STATUS UPDATE ----------
    def update_item_status(self, lot, old_items, new_items, old_status):
        added = new_items - old_items
        removed = old_items - new_items

        for item in added:
            item.status = "sold" if lot.status == "sold" else "lotted"
            item.save(update_fields=["status"])

        for item in removed:
            if not item.lots.exclude(pk=lot.pk).exists():
                item.status = "available"
                item.save(update_fields=["status"])

        if old_status != "sold" and lot.status == "sold":
            for item in new_items:
                if item.status != "sold":
                    item.status = "sold"
                    item.save(update_fields=["status"])

        if old_status == "sold" and lot.status != "sold":
            for item in new_items:
                if item.status == "sold":
                    item.status = "lotted"
                    item.save(update_fields=["status"])

    # ---------- STARTING BID ----------
    def calculate_starting_bid(self, lot, old_items, new_items):
        if old_items != new_items and lot.items.exists():
            total = lot.items.aggregate(total=Sum("estimated_value"))["total"] or 0
            lot.starting_bid = total
            lot.save(update_fields=["starting_bid"])

    # ---------- M2M FILTER ----------
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "items":
            qs = Item.objects.filter(status="available")
            if request.resolver_match and request.resolver_match.kwargs.get(
                "object_id"
            ):
                lot_id = request.resolver_match.kwargs["object_id"]
                qs = qs | Item.objects.filter(lots__id=lot_id)
            kwargs["queryset"] = qs.distinct()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    class Media:
        js = ("admin/js/lot_item_filter.js",)


class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "user",'lot','amount','issued_at'
    )

admin.site.register(LotRegister)
admin.site.register(AuctionRegister)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.site_header = "Auction Management System"
admin.site.site_title = "Auction Admin"
admin.site.index_title = "Welcome to Auction Administration"
