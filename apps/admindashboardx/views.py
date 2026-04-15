from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from bot.models import (
    Logging,
    ReferralTransaction,
    Server,
    TelegramReferral,
    TelegramUser,
    Transaction,
    UserProfile,
    VpnKey,
    WithdrawalRequest,
)


class DashboardBaseView(LoginRequiredMixin, TemplateView):
    page_title = "Admin Dashboard X"
    page_key = "index"
    login_url = "login"


    def _base_context(self):
        support_account = getattr(settings, "SUPPORT_ACCOUNT", "")
        user = self.request.user
        is_support = bool(getattr(user, "is_authenticated", False) and user.username == support_account)
        return {
            "page_title": self.page_title,
            "page_key": self.page_key,
            "is_support": is_support,
        }


    def _is_support(self):
        support_account = getattr(settings, "SUPPORT_ACCOUNT", "")
        user = self.request.user
        return bool(getattr(user, "is_authenticated", False) and user.username == support_account)

    def _paginate(self, queryset, per_page=50):
        page_number = self.request.GET.get("page", 1)
        paginator = Paginator(queryset, per_page)
        return paginator.get_page(page_number)

    def _page_qs(self):
        params = self.request.GET.copy()
        params.pop("page", None)
        return params.urlencode()

    def _safe_return_to(self, default_url):
        """
        Allow only internal admindashboardx return urls.
        Prevent open redirects and accidental jumps outside panel.
        """
        raw = (self.request.GET.get("return_to") or "").strip()
        if raw.startswith("/admindashboardx/"):
            return raw
        return default_url

    def _forbidden_response(self):
        return render(
            self.request,
            "admindashboardx/forbidden.html",
            {
                **self._base_context(),
                "page_title": "AdminDashboardX · Доступ ограничен",
                "forbidden_message": "У вас недостаточно прав для просмотра этого раздела.",
            },
            status=403,
        )


class AdminDashboardIndexView(DashboardBaseView):
    template_name = "admindashboardx/index.html"
    page_title = "AdminDashboardX · Главная"
    page_key = "index"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        period_days = 30
        since = now - timedelta(days=period_days)

        kpi_users_total = TelegramUser.objects.count()
        kpi_users_active = TelegramUser.objects.filter(subscription_status=True).count()
        kpi_users_new = TelegramUser.objects.filter(join_date__gte=since.date()).count()

        successful_tx_qs = Transaction.objects.filter(
            timestamp__gte=since,
            status="succeeded",
            paid=True,
        )
        kpi_success_tx_count = successful_tx_qs.count()
        kpi_success_tx_sum = successful_tx_qs.aggregate(total=Sum("amount")).get("total") or Decimal("0")

        error_levels = ("WARNING", "FATAL")
        kpi_error_logs = Logging.objects.filter(datetime__gte=since, log_level__in=error_levels).count()

        context.update(
            {
                **self._base_context(),
                "period_days": period_days,
                "kpi_users_total": kpi_users_total,
                "kpi_users_active": kpi_users_active,
                "kpi_users_new": kpi_users_new,
                "kpi_success_tx_count": kpi_success_tx_count,
                "kpi_success_tx_sum": kpi_success_tx_sum,
                "kpi_error_logs": kpi_error_logs,
                "recent_error_logs": Logging.objects.filter(log_level__in=error_levels)
                .select_related("user")
                .order_by("-datetime")[:20],
                "recent_failed_tx": Transaction.objects.filter(status__in=("failed", "canceled"))
                .select_related("user")
                .order_by("-timestamp")[:20],
            }
        )
        return context


class UsersListView(DashboardBaseView):
    template_name = "admindashboardx/users.html"
    page_title = "AdminDashboardX · Пользователи"
    page_key = "users"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        subscription_status = (self.request.GET.get("subscription_status") or "").strip()

        users_qs = TelegramUser.objects.only(
            "id",
            "join_date",
            "user_id",
            "username",
            "first_name",
            "last_name",
            "subscription_status",
            "subscription_expiration",
            "payment_method_id",
        ).order_by("-join_date", "-id")
        if query:
            users_qs = users_qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(user_id__icontains=query)
            )
        if subscription_status in ("true", "false"):
            users_qs = users_qs.filter(subscription_status=(subscription_status == "true"))

        context.update(
            {
                **self._base_context(),
                "users_page": self._paginate(users_qs, per_page=50),
                "q": query,
                "subscription_status": subscription_status,
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:users"),
            }
        )
        return context


class TransactionsListView(DashboardBaseView):
    template_name = "admindashboardx/transactions.html"
    page_title = "AdminDashboardX · Транзакции"
    page_key = "transactions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()

        tx_qs = Transaction.objects.select_related("user").only(
            "id",
            "timestamp",
            "amount",
            "currency",
            "status",
            "payment_system",
            "payment_id",
            "description",
            "user__user_id",
            "user__username",
        ).order_by("-timestamp", "-id")
        if query:
            tx_qs = tx_qs.filter(
                Q(payment_id__icontains=query)
                | Q(description__icontains=query)
                | Q(user__username__icontains=query)
                | Q(user__user_id__icontains=query)
            )
        if status:
            tx_qs = tx_qs.filter(status=status)

        context.update(
            {
                **self._base_context(),
                "tx_page": self._paginate(tx_qs, per_page=50),
                "q": query,
                "status": status,
                "status_choices": ("pending", "succeeded", "canceled", "failed", "refunded", "captured"),
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:transactions"),
            }
        )
        return context


class LogsListView(DashboardBaseView):
    template_name = "admindashboardx/logs.html"
    page_title = "AdminDashboardX · Логи"
    page_key = "logs"

    def post(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()

        delete_days_raw = (request.POST.get("delete_days") or "").strip()
        allowed_days = {"3", "7", "30"}
        if delete_days_raw not in allowed_days:
            return redirect(reverse("admindashboardx:logs") + "?ops=invalid")

        delete_days = int(delete_days_raw)
        cutoff = timezone.now() - timedelta(days=delete_days)
        deleted_count, _ = Logging.objects.filter(datetime__lt=cutoff).delete()
        return redirect(
            reverse("admindashboardx:logs")
            + f"?ops=deleted&days={delete_days}&count={deleted_count}"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        level = (self.request.GET.get("level") or "").strip()
        ops = (self.request.GET.get("ops") or "").strip()
        deleted_days = (self.request.GET.get("days") or "").strip()
        deleted_count = (self.request.GET.get("count") or "").strip()

        logs_qs = Logging.objects.select_related("user").only(
            "id",
            "datetime",
            "log_level",
            "message",
            "user__user_id",
        ).order_by("-datetime", "-id")
        if query:
            logs_qs = logs_qs.filter(Q(message__icontains=query) | Q(user__user_id__icontains=query))
        if level:
            logs_qs = logs_qs.filter(log_level=level)

        context.update(
            {
                **self._base_context(),
                "logs_page": self._paginate(logs_qs, per_page=50),
                "q": query,
                "level": level,
                "level_choices": ("TRACE", "DEBUG", "INFO", "WARNING", "FATAL", "SUCCESS"),
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:logs"),
                "ops": ops,
                "deleted_days": deleted_days,
                "deleted_count": deleted_count,
            }
        )
        return context


class ServersListView(DashboardBaseView):
    template_name = "admindashboardx/servers.html"
    page_title = "AdminDashboardX · Серверы"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        is_active = (self.request.GET.get("is_active") or "").strip()

        servers_qs = Server.objects.select_related("country").only(
            "id",
            "hosting",
            "ip_address",
            "is_active",
            "is_activated_vless",
            "keys_generated",
            "max_keys",
            "created_at",
            "country__id",
            "country__name",
            "country__name_for_app",
        ).order_by("-created_at", "-id")
        if query:
            servers_qs = servers_qs.filter(
                Q(hosting__icontains=query) | Q(ip_address__icontains=query) | Q(country__name_for_app__icontains=query)
            )
        if is_active in ("true", "false"):
            servers_qs = servers_qs.filter(is_active=(is_active == "true"))

        context.update(
            {
                **self._base_context(),
                "servers_page": self._paginate(servers_qs, per_page=50),
                "q": query,
                "is_active": is_active,
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:servers"),
            }
        )
        return context


class KeysListView(DashboardBaseView):
    template_name = "admindashboardx/keys.html"
    page_title = "AdminDashboardX · Ключи"
    page_key = "keys"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        protocol = (self.request.GET.get("protocol") or "").strip()

        keys_qs = VpnKey.objects.select_related("user", "server").only(
            "key_id",
            "created_at",
            "protocol",
            "method",
            "access_url",
            "user__user_id",
            "user__username",
            "server__id",
            "server__hosting",
            "server__ip_address",
        ).order_by("-created_at")
        if query:
            keys_qs = keys_qs.filter(
                Q(user__user_id__icontains=query)
                | Q(user__username__icontains=query)
                | Q(server__hosting__icontains=query)
                | Q(access_url__icontains=query)
            )
        if protocol:
            keys_qs = keys_qs.filter(protocol=protocol)

        context.update(
            {
                **self._base_context(),
                "keys_page": self._paginate(keys_qs, per_page=50),
                "q": query,
                "protocol": protocol,
                "protocol_choices": ("outline", "vless"),
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:keys"),
            }
        )
        return context


class UserDetailView(DashboardBaseView):
    template_name = "admindashboardx/user_detail.html"
    page_title = "AdminDashboardX · Пользователь"
    page_key = "users"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        telegram_user_id = kwargs.get("telegram_user_id")
        user_obj = get_object_or_404(
            TelegramUser.objects.select_related("special_offer").only(
                "id",
                "join_date",
                "user_id",
                "username",
                "first_name",
                "last_name",
                "photo_url",
                "is_banned",
                "subscription_status",
                "subscription_expiration",
                "permission_revoked",
                "balance",
                "income",
                "data_limit",
                "top_up_balance_listener",
                "withdrawal_listener",
                "next_payment_date",
                "payment_method_id",
                "robokassa_recurring_parent_inv_id",
                "special_offer__level_1_percentage",
                "special_offer__level_2_percentage",
                "special_offer__level_3_percentage",
                "special_offer__level_4_percentage",
                "special_offer__level_5_percentage",
            ),
            user_id=telegram_user_id,
        )
        back_url = self._safe_return_to(reverse("admindashboardx:users"))

        user_profile = UserProfile.objects.select_related("user").filter(telegram_user=user_obj).first()
        django_user = user_profile.user if user_profile else None

        all_tx = Transaction.objects.only(
            "id",
            "timestamp",
            "amount",
            "currency",
            "payment_system",
            "status",
            "paid",
            "description",
            "payment_id",
            "robokassa_invoice_id",
            "robokassa_recurring_previous_inv_id",
            "robokassa_is_recurring_parent",
            "user_id",
        ).filter(user=user_obj).order_by("-timestamp")
        all_keys = VpnKey.objects.select_related("server").only(
            "key_id",
            "created_at",
            "protocol",
            "method",
            "port",
            "access_url",
            "used_bytes",
            "data_limit",
            "server__id",
            "server__hosting",
            "server__ip_address",
            "server__country__name_for_app",
        ).filter(user=user_obj).order_by("-created_at")
        all_logs = Logging.objects.only(
            "id",
            "datetime",
            "log_level",
            "message",
        ).filter(user=user_obj).order_by("-datetime")

        withdrawals = WithdrawalRequest.objects.only(
            "id",
            "amount",
            "status",
            "currency",
            "timestamp",
        ).filter(user=user_obj).order_by("-timestamp", "-id")

        given_referrals = TelegramReferral.objects.select_related("referred").only(
            "id",
            "level",
            "referred__user_id",
            "referred__username",
            "referred__first_name",
            "referred__last_name",
        ).filter(referrer=user_obj).order_by("level", "-id")

        received_referrals = TelegramReferral.objects.select_related("referrer").only(
            "id",
            "level",
            "referrer__user_id",
            "referrer__username",
            "referrer__first_name",
            "referrer__last_name",
        ).filter(referred=user_obj).order_by("level", "-id")

        referral_earnings_as_referrer = ReferralTransaction.objects.select_related(
            "referral", "referral__referrer", "referral__referred", "transaction"
        ).only(
            "id",
            "amount",
            "timestamp",
            "referral__level",
            "referral__referrer__user_id",
            "referral__referred__user_id",
            "transaction__id",
        ).filter(referral__referrer=user_obj).order_by("-timestamp", "-id")

        referral_earnings_as_referred = ReferralTransaction.objects.select_related(
            "referral", "referral__referrer", "referral__referred", "transaction"
        ).only(
            "id",
            "amount",
            "timestamp",
            "referral__level",
            "referral__referrer__user_id",
            "referral__referred__user_id",
            "transaction__id",
        ).filter(referral__referred=user_obj).order_by("-timestamp", "-id")

        context.update(
            {
                **self._base_context(),
                "user_obj": user_obj,
                "user_profile": user_profile,
                "django_user": django_user,
                "all_tx": all_tx,
                "all_keys": all_keys,
                "all_logs": all_logs,
                "withdrawals": withdrawals,
                "given_referrals": given_referrals,
                "received_referrals": received_referrals,
                "referral_earnings_as_referrer": referral_earnings_as_referrer,
                "referral_earnings_as_referred": referral_earnings_as_referred,
                "back_url": back_url,
                "section_url": reverse("admindashboardx:users"),
                "section_label": "Пользователи",
            }
        )
        return context


class TransactionDetailView(DashboardBaseView):
    template_name = "admindashboardx/transaction_detail.html"
    page_title = "AdminDashboardX · Транзакция"
    page_key = "transactions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tx_id = kwargs.get("tx_id")
        tx = get_object_or_404(
            Transaction.objects.select_related("user").only(
                "id",
                "timestamp",
                "status",
                "paid",
                "amount",
                "currency",
                "payment_system",
                "payment_id",
                "description",
                "robokassa_invoice_id",
                "robokassa_recurring_previous_inv_id",
                "robokassa_is_recurring_parent",
                "user__user_id",
            ),
            id=tx_id,
        )
        back_url = self._safe_return_to(reverse("admindashboardx:transactions"))
        context.update(
            {
                **self._base_context(),
                "tx": tx,
                "back_url": back_url,
                "section_url": reverse("admindashboardx:transactions"),
                "section_label": "Транзакции",
            }
        )
        return context


class ServerDetailView(DashboardBaseView):
    template_name = "admindashboardx/server_detail.html"
    page_title = "AdminDashboardX · Сервер"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        server_id = kwargs.get("server_id")
        server = get_object_or_404(
            Server.objects.select_related("country").only(
                "id",
                "hosting",
                "ip_address",
                "created_at",
                "is_active",
                "is_activated_vless",
                "keys_generated",
                "max_keys",
                "country__name",
                "country__name_for_app",
            ),
            id=server_id,
        )
        back_url = self._safe_return_to(reverse("admindashboardx:servers"))
        server_keys = VpnKey.objects.select_related("user").only(
            "key_id",
            "created_at",
            "protocol",
            "access_url",
            "user__user_id",
        ).filter(server=server).order_by("-created_at")[:30]
        context.update(
            {
                **self._base_context(),
                "server": server,
                "server_keys": server_keys,
                "back_url": back_url,
                "section_url": reverse("admindashboardx:servers"),
                "section_label": "Серверы",
            }
        )
        return context
