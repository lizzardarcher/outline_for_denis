from django.contrib import admin

from apps.mtproxy.models import ProxyAccessKey, ProxyEvent, ProxyNode, ProxyUsageSnapshot
from apps.mtproxy.tasks import (
    collect_mtproxy_usage_snapshots_task,
    calculate_mtproxy_abuse_score_task,
    healthcheck_mtproxy_nodes_task,
    install_mtproxy_node_task,
    revoke_mtproxy_keys_for_inactive_subscriptions_task,
)


# @admin.action(description="Установить ПО на выбранные ноды")
# def install_selected_nodes(modeladmin, request, queryset):
#     for node in queryset:
#         install_mtproxy_node_task.delay(node.id, force=False)
#
#
# @admin.action(description="Переустановить ПО на выбранных нодах")
# def reinstall_selected_nodes(modeladmin, request, queryset):
#     for node in queryset:
#         install_mtproxy_node_task.delay(node.id, force=True)
#
#
# @admin.action(description="Запустить health-check всех нод")
# def run_healthcheck(modeladmin, request, queryset):
#     healthcheck_mtproxy_nodes_task.delay()
#
#
# @admin.action(description="Пересчитать anti-abuse score")
# def run_abuse_scoring(modeladmin, request, queryset):
#     calculate_mtproxy_abuse_score_task.delay()
#
#
# @admin.action(description="Собрать usage snapshots")
# def collect_usage_snapshots(modeladmin, request, queryset):
#     if queryset is None or queryset.count() == 0:
#         collect_mtproxy_usage_snapshots_task.delay()
#         return
#     for node in queryset:
#         collect_mtproxy_usage_snapshots_task.delay(node_id=node.id)
#
#
# @admin.action(description="Отозвать ключи у users без подписки")
# def revoke_inactive_subscriptions_keys(modeladmin, request, queryset):
#     revoke_mtproxy_keys_for_inactive_subscriptions_task.delay()
#
#
# @admin.register(ProxyNode)
# class ProxyNodeAdmin(admin.ModelAdmin):
#     list_display = (
#         "name",
#         "country",
#         "host",
#         "proxy_port",
#         "metrics_url",
#         "is_active",
#         "is_software_installed",
#         "install_state",
#         "health_state",
#         "capacity",
#         "issued_keys_count",
#         "updated_at",
#     )
#     list_display_links = ("name", "host")
#     list_filter = ("is_active", "is_software_installed", "install_state", "health_state", "country")
#     search_fields = ("name", "host", "country__name", "country__name_for_app")
#     actions = (
#         install_selected_nodes,
#         reinstall_selected_nodes,
#         run_healthcheck,
#         collect_usage_snapshots,
#         run_abuse_scoring,
#         revoke_inactive_subscriptions_keys,
#     )
#     readonly_fields = ("issued_keys_count", "installed_at", "last_healthcheck_at", "updated_at", "created_at")
#
#     def save_model(self, request, obj, form, change):
#         created = obj.pk is None
#         super().save_model(request, obj, form, change)
#         if created and obj.auto_install_on_create and not obj.is_software_installed:
#             install_mtproxy_node_task.delay(obj.id, force=False)
#
#
# @admin.register(ProxyAccessKey)
# class ProxyAccessKeyAdmin(admin.ModelAdmin):
#     list_display = ("id", "user", "node", "status", "abuse_score", "created_at", "revoked_at")
#     list_display_links = ("id", "user")
#     list_filter = ("status", "node", "created_at", "last_abuse_check_at")
#     search_fields = ("user__user_id", "user__username", "secret", "node__host", "node__name")
#     readonly_fields = ("tg_proxy_link", "web_proxy_link", "created_at", "revoked_at", "last_abuse_check_at")
#     actions = (run_abuse_scoring, collect_usage_snapshots)
#
#
# @admin.register(ProxyUsageSnapshot)
# class ProxyUsageSnapshotAdmin(admin.ModelAdmin):
#     list_display = (
#         "id",
#         "key",
#         "concurrent_connections",
#         "new_sessions_5m",
#         "unique_ip_24h",
#         "source",
#         "captured_at",
#     )
#     list_display_links = ("id", "key")
#     list_filter = ("source", "captured_at", "key__node")
#     search_fields = ("key__user__user_id", "key__user__username", "key__node__host", "source")
#     actions = (run_abuse_scoring,)
#
#
# @admin.register(ProxyEvent)
# class ProxyEventAdmin(admin.ModelAdmin):
#     list_display = ("id", "event_type", "node", "user", "created_at")
#     list_display_links = ("id", "event_type")
#     list_filter = ("event_type", "created_at")
#     search_fields = ("message", "node__host", "user__user_id", "user__username")
#     readonly_fields = ("event_type", "node", "user", "message", "created_at")
#
#     def has_add_permission(self, request):
#         return False
#
#     def has_change_permission(self, request, obj=None):
#         return False
