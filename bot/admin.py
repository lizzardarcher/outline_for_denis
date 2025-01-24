import os

from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html
from django.conf import settings

from bot.models import *

DEBUG = settings.DEBUG
# admin.site.site_url = ''
admin.site.site_header = "Outline VPN BOT Админ Панель"
admin.site.site_title = "Outline VPN BOT"
admin.site.index_title = "Добро пожаловать в Outline VPN BOT Админ Панель"
admin.site.unregister(Group)
admin.site.unregister(User)


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


class TransactionInline(admin.TabularInline):
    model = Transaction
    fields = ('amount', 'currency', 'user', 'side')
    ordering = ['-timestamp']

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
        'join_date', 'first_name', 'last_name', 'username', 'subscription_status', 'subscription_expiration', 'balance')
    list_display_links = (
        'join_date', 'first_name', 'last_name', 'username', 'subscription_status', 'subscription_expiration', 'balance')
    search_fields = ('first_name', 'last_name', 'username', 'user_id')
    readonly_fields = ('join_date', 'first_name', 'last_name', 'username', 'user_id', 'income')
    exclude = ('data_limit', 'is_banned', 'top_up_balance_listener', 'withdrawal_listener')
    ordering = ('-subscription_status', '-join_date',)
    empty_value_display = '---'
    inlines = [TransactionInline, VpnKeyInline, WithdrawalRequestInline, LogInline]

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
    list_display = ('timestamp', 'amount', 'currency', 'user', 'side')
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


# @admin.register(GlobalSettings)
# class GlobalSettingAdmin(admin.ModelAdmin):
#     def has_add_permission(self, request):
#         if not DEBUG:
#             return False
#         else:
#             return True
#
#     def get_actions(self, request):
#         actions = super().get_actions(request)
#         if 'delete_selected' in actions:
#             del actions['delete_selected']
#         return actions
#
#     def save_model(self, request, obj, form, change):
#         """
#         Given a model instance save it to the database.
#         """
#         obj.save()
#         os.system('systemctl restart outline_for_denis-vpnbot.service')


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
        'hosting', 'ip_address', 'user', 'password', 'rental_price', 'max_keys', 'get_key_generated', 'is_active',
        'country', 'created_at')
    list_display_links = ('hosting', 'ip_address',)
    inlines = [VpnKeyInline]
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
