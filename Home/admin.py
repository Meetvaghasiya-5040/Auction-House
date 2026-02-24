from django.contrib import admin
from unfold.admin import ModelAdmin

# Register your models here.
from .models import Profile


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ["user", "created_at", "updated_at"]
    search_fields = ["user__username", "user__email"]
    list_filter = ["created_at"]
    readonly_fields = ["created_at", "updated_at"]
    list_filter_submit = True
    list_per_page = 20
