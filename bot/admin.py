import os

from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html
from django.conf import settings
from django_celery_beat.models import *
from django_admin_inline_paginator.admin import TabularInlinePaginated
from django.urls import path, reverse
from django.shortcuts import render

from bot.models import *

DEBUG = settings.DEBUG
# admin.site.site_url = ''
admin.site.site_header = "DomVPN BOT Админ Панель"
admin.site.site_title = "DomVPN BOT"
admin.site.index_title = "Добро пожаловать в DomVPN BOT Админ Панель"
admin.site.unregister(Group)
admin.site.unregister(User)
admin.site.unregister(CrontabSchedule)
admin.site.unregister(SolarSchedule)
admin.site.unregister(ClockedSchedule)


class WithdrawalRequestInline(admin.TabularInline):
    model = WithdrawalRequest

    def has_add_permission(self, request, obj):
        if not DEBUG:
            return False
        else:
            return True

    def has_delete_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_change_permission(self, request, obj=None):
        return False


class TransactionInline(TabularInlinePaginated, admin.TabularInline):
    model = Transaction
    fields = ('amount', 'currency', 'user', 'side')
    ordering = ['-timestamp']
    per_page = 50
    def has_add_permission(self, request, obj):
        if not DEBUG:
            return False
        else:
            return True

    def has_delete_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_change_permission(self, request, obj=None):
        return False


class VpnKeyInline(admin.TabularInline):
    model = VpnKey
    list_display_links = ('key_id', 'access_url')
    def has_add_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_delete_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_change_permission(self, request, obj=None):
        return False


class ServerInline(admin.TabularInline):
    model = Server
    extra = 1

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class LogInline(admin.TabularInline):
    model = Logging
    fields = ('user', 'message')
    ordering = ['-datetime']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = (
        'join_date', 'first_name', 'last_name', 'username', 'subscription_status',
        'subscription_expiration', 'balance', 'referral_link', 'get_payment_method_id', 'permission_revoked', 'income')
    list_display_links = (
        'join_date', 'first_name', 'last_name', 'username', 'subscription_status', 'subscription_expiration', 'balance', 'income')
    search_fields = ('first_name', 'last_name', 'username', 'user_id')
    readonly_fields = ('join_date', 'first_name', 'last_name', 'username', 'user_id',)
    exclude = ('data_limit', 'is_banned', 'top_up_balance_listener', 'withdrawal_listener')
    ordering = ('-subscription_status', '-join_date',)
    empty_value_display = '---'
    inlines = [TransactionInline, VpnKeyInline, WithdrawalRequestInline, LogInline]

    def referral_link(self, obj):
        referral_url = f"https://t.me/xDomvpn_Bot?start={obj.user_id}"
        return format_html('{}', referral_url, referral_url)

    def get_payment_method_id(self, obj):
        payment_method_id = obj.payment_method_id
        if payment_method_id:
            return '✅'
        else:
            return '---'
    referral_link.short_description = 'Referral Link'
    get_payment_method_id.short_description = 'Payment Method ID'

    def has_add_permission(self, request):
        if not DEBUG:
            return False
        else:
            return True

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions


@admin.register(TelegramBot)
class TelegramBotAdmin(admin.ModelAdmin):
    list_display = ('title', 'token', 'username', 'created_at')

    def has_add_permission(self, request):
        if TelegramBot.objects.all():
            return False
        else:
            return True

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions

    def save_model(self, request, obj, form, change):
        """
        Given a model instance save it to the database.
        """
        obj.save()
        os.system('systemctl restart outline_for_denis-vpnbot.service')


@admin.register(TelegramReferral)
class TelegramReferralAdmin(admin.ModelAdmin):
    list_display = ('referrer', 'referred', 'level')
    search_fields = ('referrer__username', 'referred__username', 'referrer__first_name', 'referred__first_name',
                     'referrer__last_name', 'referred__last_name', 'referrer__user_id', 'referred__user_id')
    def has_add_permission(self, request):
        if not DEBUG:
            return False
        else:
            return True

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'amount', 'currency', 'status','description','paid','payment_id',  'user', 'side')
    list_display_links = ('user',)
    ordering = ['-timestamp']

    def has_add_permission(self, request):
        if not DEBUG:
            return False
        else:
            return True

    def has_delete_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_change_permission(self, request, obj=None):
        return False


    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'status', 'currency', 'timestamp')
    list_editable = ['status']

    def has_add_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    # def has_delete_permission(self, request, obj=None):
    #     return False


@admin.register(ReferralSettings)
class ReferralSettingAdmin(admin.ModelAdmin):

    def has_add_permission(self, request):
        if not DEBUG:
            return False
        else:
            return True

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions


@admin.register(IncomeInfo)
class IncomeInfo(admin.ModelAdmin):
    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions

    readonly_fields = ('total_amount', 'user_balance_total')
    inlines = [TransactionInline]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(VpnKey)
class VpnKey(admin.ModelAdmin):
    list_display = ('user', 'server', 'access_url', 'data_limit', 'created_at')
    list_display_links = ('user', 'server', 'access_url', 'data_limit', 'created_at')
    search_fields = ('access_url',)
    list_filter = ('server',)
    ordering = ['server']
    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):

    def get_key_generated(self, obj):
        if 0 < obj.keys_generated <= 100:
            return format_html('<b style="color:green;">%s</b>' % obj.keys_generated)
        elif 100 < obj.keys_generated <= 150:
            return format_html('<b style="color:yellow;">%s</b>' % obj.keys_generated)
        elif obj.keys_generated > 150:
            return format_html('<b style="color:red;">%s</b>' % obj.keys_generated)


    get_key_generated.allow_tags = True
    get_key_generated.short_description = 'Всего ключей'

    list_display = (
        'hosting', 'ip_address', 'user', 'password', 'rental_price', 'max_keys', 'get_key_generated', 'is_active', 'is_activated', 'is_activated_vless',
        'country', 'created_at')
    list_display_links = ('hosting', 'ip_address',)
    # inlines = [VpnKeyInline]
    ordering = ('country', 'ip_address')


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('name_for_app', 'is_active', 'name')
    list_display_links = ('name_for_app', 'name')
    inlines = [ServerInline]


@admin.action(description="Пометить как TRACE")
def make_trace(modeladmin, request, queryset):
    queryset.update(log_level="TRACE")


@admin.action(description="Пометить как DEBUG")
def make_debug(modeladmin, request, queryset):
    queryset.update(log_level="DEBUG")


@admin.action(description="Пометить как INFO")
def make_info(modeladmin, request, queryset):
    queryset.update(log_level="INFO")


@admin.action(description="Пометить как FATAL")
def make_fatal(modeladmin, request, queryset):
    queryset.update(log_level="FATAL")


@admin.action(description="Пометить как WARNING")
def make_warning(modeladmin, request, queryset):
    queryset.update(log_level="WARNING")


@admin.action(description="Пометить как SUCCESS")
def make_success(modeladmin, request, queryset):
    queryset.update(log_level="SUCCESS")


@admin.register(Logging)
class LoggingAdmin(admin.ModelAdmin):

    def get_log_level(self, obj):
        if obj.log_level == 'INFO':
            return format_html('<div style="color:aqua;">%s</div>' % obj.log_level)
        elif obj.log_level == 'FATAL':
            return format_html('<div style="color:red;">%s</div>' % obj.log_level)
        elif obj.log_level == 'WARNING':
            return format_html('<div style="color:orange;">%s</div>' % obj.log_level)
        elif obj.log_level == 'TRACE':
            return format_html('<div style="color:white;">%s</div>' % obj.log_level)
        elif obj.log_level == 'DEBUG':
            return format_html('<div style="color:white;">%s</div>' % obj.log_level)
        elif obj.log_level == 'SUCCESS':
            return format_html('<div style="color:green; font-weight: bold;">%s</div>' % obj.log_level)
        return obj.log_level

    get_log_level.allow_tags = True
    get_log_level.short_description = 'log_level'

    list_display = ('datetime', 'user', 'message', 'get_log_level',)
    list_display_links = ('user', 'message',)
    search_fields = ('message', 'user__username',)
    ordering = ['-datetime']
    actions = [make_warning, make_debug, make_fatal, make_trace, make_success, make_info]

    def has_add_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True


@admin.register(User)
class UserAdmin(admin.ModelAdmin):

    def has_add_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True

    def has_delete_permission(self, request, obj=None):
        if not DEBUG:
            return False
        else:
            return True


@admin.register(Prices)
class PricesAdmin(admin.ModelAdmin):

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram_user', 'referral_link')
    readonly_fields = ('referral_link',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'telegram_user__user_id', 'telegram_user__username')  # Search on related fields
    list_filter = ('telegram_user__is_banned', 'telegram_user__subscription_status') # Filter by telegram user status.

    def referral_link(self, obj):
        """
        Generates the referral link for the associated TelegramUser.
        Returns an empty string if there's no associated TelegramUser.
        """
        if obj.telegram_user:
            referral_url = f"https://t.me/xDomvpn_Bot?start={obj.telegram_user.user_id}"
            return format_html('{}', referral_url, referral_url)
        else:
            return "No Telegram User"  # Or any appropriate message

    referral_link.short_description = 'Referral Link'

@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    readonly_fields = ('status', 'counter')


