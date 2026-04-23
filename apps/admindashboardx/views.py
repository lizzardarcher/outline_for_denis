from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django import forms
from django.forms import modelform_factory
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from bot.models import (
    Country,
    IncomeInfo,
    Logging,
    Prices,
    ReferralSettings,
    ReferralTransaction,
    ReferralSpecialOffer,
    Server,
    SiteNotification,
    SiteNotificationState,
    TelegramBot,
    TelegramReferral,
    TelegramMessage,
    TelegramUser,
    Transaction,
    UserProfile,
    VpnKey,
    WithdrawalRequest,
)
from .tasks import initialize_server_task

class ServerForm(forms.ModelForm):
    class Meta:
        model = Server
        fields = (
            "hosting",
            "ip_address",
            "user",
            "password",
            "rental_price",
            "keys_generated",
            "is_active",
            "country",
        )
        widgets = {
            "password": forms.PasswordInput(render_value=True, attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("is_active",):
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()
        self.fields["country"].queryset = Country.objects.filter(is_active=True).order_by("name_for_app", "name")


class CountryForm(forms.ModelForm):
    class Meta:
        model = Country
        fields = ("name", "name_for_app", "preset_id", "is_active")
        widgets = {
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "is_active":
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


class PricesForm(forms.ModelForm):
    class Meta:
        model = Prices
        fields = ("price_1", "price_2", "price_3", "price_4", "price_5")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


class TelegramMessageForm(forms.ModelForm):
    class Meta:
        model = TelegramMessage
        fields = ("text", "status", "send_to_subscribed", "send_to_notsubscribed", "counter")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 5}),
            "send_to_subscribed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "send_to_notsubscribed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("send_to_subscribed", "send_to_notsubscribed"):
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


class SiteNotificationForm(forms.ModelForm):
    class Meta:
        model = SiteNotification
        fields = ("title", "message", "is_active", "starts_at", "expires_at")
        widgets = {
            "message": forms.Textarea(attrs={"rows": 5}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "is_active":
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


class SiteNotificationStateForm(forms.ModelForm):
    class Meta:
        model = SiteNotificationState
        fields = ("user", "last_seen_notification_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-control".strip()


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


class ServerCreateView(DashboardBaseView):
    template_name = "admindashboardx/server_form.html"
    page_title = "AdminDashboardX · Новый сервер"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or ServerForm()
        context.update(
            {
                **self._base_context(),
                "form": form,
                "form_title": "Создать сервер",
                "submit_label": "Создать",
                "back_url": reverse("admindashboardx:servers"),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form = ServerForm(request.POST)
        if form.is_valid():
            server = form.save()
            return redirect(reverse("admindashboardx:server_detail", kwargs={"server_id": server.id}) + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class ServerUpdateView(DashboardBaseView):
    template_name = "admindashboardx/server_form.html"
    page_title = "AdminDashboardX · Редактирование сервера"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_server(self):
        return get_object_or_404(Server, id=self.kwargs.get("server_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        server = kwargs.get("server") or self.get_server()
        form = kwargs.get("form") or ServerForm(instance=server)
        context.update(
            {
                **self._base_context(),
                "server": server,
                "form": form,
                "form_title": f"Редактировать сервер #{server.id}",
                "submit_label": "Сохранить",
                "back_url": reverse("admindashboardx:server_detail", kwargs={"server_id": server.id}),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        server = self.get_server()
        form = ServerForm(request.POST, instance=server)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:server_detail", kwargs={"server_id": server.id}) + "?ops=updated")
        return self.render_to_response(self.get_context_data(server=server, form=form))


class ServerDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление сервера"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        server = get_object_or_404(Server, id=kwargs.get("server_id"))
        server.delete()
        return redirect(reverse("admindashboardx:servers") + "?ops=deleted")


class ServerInitActionView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Инициализация сервера"
    page_key = "servers"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        server = get_object_or_404(Server, id=kwargs.get("server_id"))
        initialize_server_task.delay(server.id)
        return redirect(reverse("admindashboardx:server_detail", kwargs={"server_id": server.id}) + "?ops=init_started")


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


class CountriesListView(DashboardBaseView):
    template_name = "admindashboardx/countries.html"
    page_title = "AdminDashboardX · Страны"
    page_key = "countries"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        is_active = (self.request.GET.get("is_active") or "").strip()
        ops = (self.request.GET.get("ops") or "").strip()

        countries_qs = Country.objects.only(
            "id",
            "name",
            "name_for_app",
            "preset_id",
            "is_active",
        ).order_by("name_for_app", "name", "id")
        if query:
            countries_qs = countries_qs.filter(
                Q(name__icontains=query)
                | Q(name_for_app__icontains=query)
                | Q(preset_id__icontains=query)
            )
        if is_active in ("true", "false"):
            countries_qs = countries_qs.filter(is_active=(is_active == "true"))

        context.update(
            {
                **self._base_context(),
                "countries_page": self._paginate(countries_qs, per_page=50),
                "q": query,
                "is_active": is_active,
                "ops": ops,
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:countries"),
            }
        )
        return context


class CountryCreateView(DashboardBaseView):
    template_name = "admindashboardx/country_form.html"
    page_title = "AdminDashboardX · Новая страна"
    page_key = "countries"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or CountryForm()
        context.update(
            {
                **self._base_context(),
                "form": form,
                "form_title": "Создать страну",
                "submit_label": "Создать",
                "back_url": reverse("admindashboardx:countries"),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form = CountryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:countries") + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class CountryUpdateView(DashboardBaseView):
    template_name = "admindashboardx/country_form.html"
    page_title = "AdminDashboardX · Редактирование страны"
    page_key = "countries"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_country(self):
        return get_object_or_404(Country, id=self.kwargs.get("country_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        country = kwargs.get("country") or self.get_country()
        form = kwargs.get("form") or CountryForm(instance=country)
        context.update(
            {
                **self._base_context(),
                "country": country,
                "form": form,
                "form_title": f"Редактировать страну #{country.id}",
                "submit_label": "Сохранить",
                "back_url": reverse("admindashboardx:countries"),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        country = self.get_country()
        form = CountryForm(request.POST, instance=country)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:countries") + "?ops=updated")
        return self.render_to_response(self.get_context_data(country=country, form=form))


class CountryDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление страны"
    page_key = "countries"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        country = get_object_or_404(Country, id=kwargs.get("country_id"))
        if Server.objects.filter(country=country).exists():
            return redirect(reverse("admindashboardx:countries") + "?ops=blocked")
        country.delete()
        return redirect(reverse("admindashboardx:countries") + "?ops=deleted")


class PricesListView(DashboardBaseView):
    template_name = "admindashboardx/prices.html"
    page_title = "AdminDashboardX · Цены"
    page_key = "prices"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ops = (self.request.GET.get("ops") or "").strip()
        items_qs = Prices.objects.only("id", "price_1", "price_2", "price_3", "price_4", "price_5").order_by("id")
        context.update(
            {
                **self._base_context(),
                "items_page": self._paginate(items_qs, per_page=50),
                "ops": ops,
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:prices"),
            }
        )
        return context


class PricesCreateView(DashboardBaseView):
    template_name = "admindashboardx/prices_form.html"
    page_title = "AdminDashboardX · Новая цена"
    page_key = "prices"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or PricesForm()
        context.update({**self._base_context(), "form": form, "form_title": "Создать запись цен", "submit_label": "Создать", "back_url": reverse("admindashboardx:prices")})
        return context

    def post(self, request, *args, **kwargs):
        form = PricesForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:prices") + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class PricesUpdateView(DashboardBaseView):
    template_name = "admindashboardx/prices_form.html"
    page_title = "AdminDashboardX · Редактирование цены"
    page_key = "prices"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_item(self):
        return get_object_or_404(Prices, id=self.kwargs.get("item_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = kwargs.get("item") or self.get_item()
        form = kwargs.get("form") or PricesForm(instance=item)
        context.update({**self._base_context(), "form": form, "form_title": f"Редактировать цены #{item.id}", "submit_label": "Сохранить", "back_url": reverse("admindashboardx:prices")})
        return context

    def post(self, request, *args, **kwargs):
        item = self.get_item()
        form = PricesForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:prices") + "?ops=updated")
        return self.render_to_response(self.get_context_data(item=item, form=form))


class PricesDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление цены"
    page_key = "prices"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        get_object_or_404(Prices, id=kwargs.get("item_id")).delete()
        return redirect(reverse("admindashboardx:prices") + "?ops=deleted")


class TelegramMessagesListView(DashboardBaseView):
    template_name = "admindashboardx/telegram_messages.html"
    page_title = "AdminDashboardX · Telegram сообщения"
    page_key = "telegram_messages"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ops = (self.request.GET.get("ops") or "").strip()
        items_qs = TelegramMessage.objects.only(
            "id", "text", "created_at", "status", "send_to_subscribed", "send_to_notsubscribed", "counter"
        ).order_by("-created_at", "-id")
        context.update({**self._base_context(), "items_page": self._paginate(items_qs, per_page=50), "ops": ops, "page_qs": self._page_qs(), "reset_url": reverse("admindashboardx:telegram_messages")})
        return context


class TelegramMessageCreateView(DashboardBaseView):
    template_name = "admindashboardx/telegram_message_form.html"
    page_title = "AdminDashboardX · Новое Telegram сообщение"
    page_key = "telegram_messages"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or TelegramMessageForm()
        context.update({**self._base_context(), "form": form, "form_title": "Создать Telegram сообщение", "submit_label": "Создать", "back_url": reverse("admindashboardx:telegram_messages")})
        return context

    def post(self, request, *args, **kwargs):
        form = TelegramMessageForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:telegram_messages") + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class TelegramMessageUpdateView(DashboardBaseView):
    template_name = "admindashboardx/telegram_message_form.html"
    page_title = "AdminDashboardX · Редактирование Telegram сообщения"
    page_key = "telegram_messages"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_item(self):
        return get_object_or_404(TelegramMessage, id=self.kwargs.get("item_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = kwargs.get("item") or self.get_item()
        form = kwargs.get("form") or TelegramMessageForm(instance=item)
        context.update({**self._base_context(), "form": form, "form_title": f"Редактировать Telegram сообщение #{item.id}", "submit_label": "Сохранить", "back_url": reverse("admindashboardx:telegram_messages")})
        return context

    def post(self, request, *args, **kwargs):
        item = self.get_item()
        form = TelegramMessageForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:telegram_messages") + "?ops=updated")
        return self.render_to_response(self.get_context_data(item=item, form=form))


class TelegramMessageDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление Telegram сообщения"
    page_key = "telegram_messages"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        get_object_or_404(TelegramMessage, id=kwargs.get("item_id")).delete()
        return redirect(reverse("admindashboardx:telegram_messages") + "?ops=deleted")


class SiteNotificationsListView(DashboardBaseView):
    template_name = "admindashboardx/site_notifications.html"
    page_title = "AdminDashboardX · Site уведомления"
    page_key = "site_notifications"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ops = (self.request.GET.get("ops") or "").strip()
        items_qs = SiteNotification.objects.only("id", "title", "is_active", "created_at", "starts_at", "expires_at").order_by("-id")
        context.update({**self._base_context(), "items_page": self._paginate(items_qs, per_page=50), "ops": ops, "page_qs": self._page_qs(), "reset_url": reverse("admindashboardx:site_notifications")})
        return context


class SiteNotificationCreateView(DashboardBaseView):
    template_name = "admindashboardx/site_notification_form.html"
    page_title = "AdminDashboardX · Новое site уведомление"
    page_key = "site_notifications"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or SiteNotificationForm()
        context.update({**self._base_context(), "form": form, "form_title": "Создать site уведомление", "submit_label": "Создать", "back_url": reverse("admindashboardx:site_notifications")})
        return context

    def post(self, request, *args, **kwargs):
        form = SiteNotificationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:site_notifications") + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class SiteNotificationUpdateView(DashboardBaseView):
    template_name = "admindashboardx/site_notification_form.html"
    page_title = "AdminDashboardX · Редактирование site уведомления"
    page_key = "site_notifications"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_item(self):
        return get_object_or_404(SiteNotification, id=self.kwargs.get("item_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = kwargs.get("item") or self.get_item()
        form = kwargs.get("form") or SiteNotificationForm(instance=item)
        context.update({**self._base_context(), "form": form, "form_title": f"Редактировать site уведомление #{item.id}", "submit_label": "Сохранить", "back_url": reverse("admindashboardx:site_notifications")})
        return context

    def post(self, request, *args, **kwargs):
        item = self.get_item()
        form = SiteNotificationForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:site_notifications") + "?ops=updated")
        return self.render_to_response(self.get_context_data(item=item, form=form))


class SiteNotificationDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление site уведомления"
    page_key = "site_notifications"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        get_object_or_404(SiteNotification, id=kwargs.get("item_id")).delete()
        return redirect(reverse("admindashboardx:site_notifications") + "?ops=deleted")


class SiteNotificationStatesListView(DashboardBaseView):
    template_name = "admindashboardx/site_notification_states.html"
    page_title = "AdminDashboardX · Состояния уведомлений"
    page_key = "site_notification_states"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ops = (self.request.GET.get("ops") or "").strip()
        items_qs = SiteNotificationState.objects.select_related("user").only(
            "id", "last_seen_notification_id", "updated_at", "user__user_id", "user__username"
        ).order_by("-updated_at", "-id")
        context.update({**self._base_context(), "items_page": self._paginate(items_qs, per_page=50), "ops": ops, "page_qs": self._page_qs(), "reset_url": reverse("admindashboardx:site_notification_states")})
        return context


class SiteNotificationStateCreateView(DashboardBaseView):
    template_name = "admindashboardx/site_notification_state_form.html"
    page_title = "AdminDashboardX · Новое состояние уведомлений"
    page_key = "site_notification_states"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or SiteNotificationStateForm()
        context.update({**self._base_context(), "form": form, "form_title": "Создать состояние уведомлений", "submit_label": "Создать", "back_url": reverse("admindashboardx:site_notification_states")})
        return context

    def post(self, request, *args, **kwargs):
        form = SiteNotificationStateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:site_notification_states") + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class SiteNotificationStateUpdateView(DashboardBaseView):
    template_name = "admindashboardx/site_notification_state_form.html"
    page_title = "AdminDashboardX · Редактирование состояния уведомлений"
    page_key = "site_notification_states"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_item(self):
        return get_object_or_404(SiteNotificationState, id=self.kwargs.get("item_id"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = kwargs.get("item") or self.get_item()
        form = kwargs.get("form") or SiteNotificationStateForm(instance=item)
        context.update({**self._base_context(), "form": form, "form_title": f"Редактировать состояние уведомлений #{item.id}", "submit_label": "Сохранить", "back_url": reverse("admindashboardx:site_notification_states")})
        return context

    def post(self, request, *args, **kwargs):
        item = self.get_item()
        form = SiteNotificationStateForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect(reverse("admindashboardx:site_notification_states") + "?ops=updated")
        return self.render_to_response(self.get_context_data(item=item, form=form))


class SiteNotificationStateDeleteView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Удаление состояния уведомлений"
    page_key = "site_notification_states"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        get_object_or_404(SiteNotificationState, id=kwargs.get("item_id")).delete()
        return redirect(reverse("admindashboardx:site_notification_states") + "?ops=deleted")


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
        ops = (self.request.GET.get("ops") or "").strip()
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
                "ops": ops,
            }
        )
        return context


class GenericCRUDListView(DashboardBaseView):
    template_name = "admindashboardx/generic_model_list.html"
    model = None
    page_key = ""
    page_title = "AdminDashboardX · Список"
    list_fields = ("id",)
    search_fields = ()
    reset_url_name = ""
    create_url_name = ""
    edit_url_name = ""
    delete_url_name = ""
    item_label = "запись"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        ops = (self.request.GET.get("ops") or "").strip()
        qs = self.model.objects.all().order_by("-id")
        if query and self.search_fields:
            predicate = Q()
            for field in self.search_fields:
                predicate |= Q(**{f"{field}__icontains": query})
            qs = qs.filter(predicate)
        context.update(
            {
                **self._base_context(),
                "items_page": self._paginate(qs, per_page=50),
                "q": query,
                "ops": ops,
                "list_fields": self.list_fields,
                "item_label": self.item_label,
                "page_qs": self._page_qs(),
                "reset_url": reverse(self.reset_url_name),
                "create_url": reverse(self.create_url_name),
                "edit_url_name": self.edit_url_name,
                "delete_url_name": self.delete_url_name,
            }
        )
        return context


class GenericCRUDCreateView(DashboardBaseView):
    template_name = "admindashboardx/generic_model_form.html"
    model = None
    page_key = ""
    list_url_name = ""
    form_title = "Создать"
    submit_label = "Создать"
    fields = "__all__"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def _form_class(self):
        return modelform_factory(self.model, fields=self.fields)

    def _decorate_form(self, form):
        for field in form.fields.values():
            css = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = f"{css} form-control".strip()
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or self._form_class()()
        form = self._decorate_form(form)
        context.update(
            {
                **self._base_context(),
                "form": form,
                "form_title": self.form_title,
                "submit_label": self.submit_label,
                "back_url": reverse(self.list_url_name),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form = self._form_class()(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse(self.list_url_name) + "?ops=created")
        return self.render_to_response(self.get_context_data(form=form))


class GenericCRUDUpdateView(GenericCRUDCreateView):
    submit_label = "Сохранить"

    def get_item(self):
        return get_object_or_404(self.model, id=self.kwargs.get("item_id"))

    def get_context_data(self, **kwargs):
        item = kwargs.get("item") or self.get_item()
        form = kwargs.get("form") or self._form_class()(instance=item)
        return super().get_context_data(form=form)

    def post(self, request, *args, **kwargs):
        item = self.get_item()
        form = self._form_class()(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect(reverse(self.list_url_name) + "?ops=updated")
        return self.render_to_response(self.get_context_data(item=item, form=form))


class GenericCRUDDeleteView(DashboardBaseView, View):
    model = None
    page_key = ""
    list_url_name = ""

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        item = get_object_or_404(self.model, id=self.kwargs.get("item_id"))
        try:
            item.delete()
            return redirect(reverse(self.list_url_name) + "?ops=deleted")
        except Exception:
            return redirect(reverse(self.list_url_name) + "?ops=blocked")


class IncomeInfoListView(GenericCRUDListView):
    model = IncomeInfo; page_key = "income_info"; page_title = "AdminDashboardX · IncomeInfo"
    list_fields = ("id", "total_amount", "user_balance_total")
    reset_url_name = "admindashboardx:income_info"; create_url_name = "admindashboardx:income_info_create"
    edit_url_name = "admindashboardx:income_info_update"; delete_url_name = "admindashboardx:income_info_delete"; item_label = "income info"
class IncomeInfoCreateView(GenericCRUDCreateView): model = IncomeInfo; page_key = "income_info"; list_url_name = "admindashboardx:income_info"; form_title = "Создать IncomeInfo"
class IncomeInfoUpdateView(GenericCRUDUpdateView): model = IncomeInfo; page_key = "income_info"; list_url_name = "admindashboardx:income_info"; form_title = "Редактировать IncomeInfo"
class IncomeInfoDeleteView(GenericCRUDDeleteView): model = IncomeInfo; page_key = "income_info"; list_url_name = "admindashboardx:income_info"

class ReferralSettingsListView(GenericCRUDListView):
    model = ReferralSettings; page_key = "referral_settings"; page_title = "AdminDashboardX · ReferralSettings"
    list_fields = ("id", "level_1_percentage", "level_2_percentage", "level_3_percentage", "level_4_percentage", "level_5_percentage")
    reset_url_name = "admindashboardx:referral_settings"; create_url_name = "admindashboardx:referral_settings_create"
    edit_url_name = "admindashboardx:referral_settings_update"; delete_url_name = "admindashboardx:referral_settings_delete"; item_label = "referral settings"
class ReferralSettingsCreateView(GenericCRUDCreateView): model = ReferralSettings; page_key = "referral_settings"; list_url_name = "admindashboardx:referral_settings"; form_title = "Создать ReferralSettings"
class ReferralSettingsUpdateView(GenericCRUDUpdateView): model = ReferralSettings; page_key = "referral_settings"; list_url_name = "admindashboardx:referral_settings"; form_title = "Редактировать ReferralSettings"
class ReferralSettingsDeleteView(GenericCRUDDeleteView): model = ReferralSettings; page_key = "referral_settings"; list_url_name = "admindashboardx:referral_settings"

class VpnKeyCRUDListView(GenericCRUDListView):
    model = VpnKey; page_key = "vpnkey_crud"; page_title = "AdminDashboardX · VpnKey CRUD"
    list_fields = ("key_id", "protocol", "port", "method", "created_at", "user", "server")
    search_fields = ("key_id", "protocol", "method")
    reset_url_name = "admindashboardx:vpnkey_crud"; create_url_name = "admindashboardx:vpnkey_create"
    edit_url_name = "admindashboardx:vpnkey_update"; delete_url_name = "admindashboardx:vpnkey_delete"; item_label = "vpn key"
class VpnKeyCreateView(GenericCRUDCreateView): model = VpnKey; page_key = "vpnkey_crud"; list_url_name = "admindashboardx:vpnkey_crud"; form_title = "Создать VpnKey"; fields = "__all__"
class VpnKeyUpdateView(GenericCRUDUpdateView): model = VpnKey; page_key = "vpnkey_crud"; list_url_name = "admindashboardx:vpnkey_crud"; form_title = "Редактировать VpnKey"; fields = "__all__"
class VpnKeyDeleteView(GenericCRUDDeleteView): model = VpnKey; page_key = "vpnkey_crud"; list_url_name = "admindashboardx:vpnkey_crud"

class TelegramUserCRUDListView(GenericCRUDListView):
    model = TelegramUser; page_key = "telegram_users_crud"; page_title = "AdminDashboardX · TelegramUser CRUD"
    list_fields = ("id", "user_id", "username", "first_name", "last_name", "subscription_status")
    search_fields = ("user_id", "username", "first_name", "last_name")
    reset_url_name = "admindashboardx:telegram_users_crud"; create_url_name = "admindashboardx:telegram_user_create"
    edit_url_name = "admindashboardx:telegram_user_update"; delete_url_name = "admindashboardx:telegram_user_delete"; item_label = "telegram user"
class TelegramUserCreateView(GenericCRUDCreateView): model = TelegramUser; page_key = "telegram_users_crud"; list_url_name = "admindashboardx:telegram_users_crud"; form_title = "Создать TelegramUser"
class TelegramUserUpdateView(GenericCRUDUpdateView): model = TelegramUser; page_key = "telegram_users_crud"; list_url_name = "admindashboardx:telegram_users_crud"; form_title = "Редактировать TelegramUser"
class TelegramUserDeleteView(GenericCRUDDeleteView): model = TelegramUser; page_key = "telegram_users_crud"; list_url_name = "admindashboardx:telegram_users_crud"

class UserProfileCRUDListView(GenericCRUDListView):
    model = UserProfile; page_key = "user_profile_crud"; page_title = "AdminDashboardX · UserProfile CRUD"
    list_fields = ("id", "user", "telegram_user", "site_password_generated")
    reset_url_name = "admindashboardx:user_profile_crud"; create_url_name = "admindashboardx:user_profile_create"
    edit_url_name = "admindashboardx:user_profile_update"; delete_url_name = "admindashboardx:user_profile_delete"; item_label = "user profile"
class UserProfileCreateView(GenericCRUDCreateView): model = UserProfile; page_key = "user_profile_crud"; list_url_name = "admindashboardx:user_profile_crud"; form_title = "Создать UserProfile"
class UserProfileUpdateView(GenericCRUDUpdateView): model = UserProfile; page_key = "user_profile_crud"; list_url_name = "admindashboardx:user_profile_crud"; form_title = "Редактировать UserProfile"
class UserProfileDeleteView(GenericCRUDDeleteView): model = UserProfile; page_key = "user_profile_crud"; list_url_name = "admindashboardx:user_profile_crud"

class TelegramReferralCRUDListView(GenericCRUDListView):
    model = TelegramReferral; page_key = "telegram_referral_crud"; page_title = "AdminDashboardX · TelegramReferral CRUD"
    list_fields = ("id", "referrer", "referred", "level")
    reset_url_name = "admindashboardx:telegram_referral_crud"; create_url_name = "admindashboardx:telegram_referral_create"
    edit_url_name = "admindashboardx:telegram_referral_update"; delete_url_name = "admindashboardx:telegram_referral_delete"; item_label = "telegram referral"
class TelegramReferralCreateView(GenericCRUDCreateView): model = TelegramReferral; page_key = "telegram_referral_crud"; list_url_name = "admindashboardx:telegram_referral_crud"; form_title = "Создать TelegramReferral"
class TelegramReferralUpdateView(GenericCRUDUpdateView): model = TelegramReferral; page_key = "telegram_referral_crud"; list_url_name = "admindashboardx:telegram_referral_crud"; form_title = "Редактировать TelegramReferral"
class TelegramReferralDeleteView(GenericCRUDDeleteView): model = TelegramReferral; page_key = "telegram_referral_crud"; list_url_name = "admindashboardx:telegram_referral_crud"

class ReferralTransactionCRUDListView(GenericCRUDListView):
    model = ReferralTransaction; page_key = "referral_transaction_crud"; page_title = "AdminDashboardX · ReferralTransaction CRUD"
    list_fields = ("id", "referral", "transaction", "amount", "timestamp")
    reset_url_name = "admindashboardx:referral_transaction_crud"; create_url_name = "admindashboardx:referral_transaction_create"
    edit_url_name = "admindashboardx:referral_transaction_update"; delete_url_name = "admindashboardx:referral_transaction_delete"; item_label = "referral transaction"
class ReferralTransactionCreateView(GenericCRUDCreateView): model = ReferralTransaction; page_key = "referral_transaction_crud"; list_url_name = "admindashboardx:referral_transaction_crud"; form_title = "Создать ReferralTransaction"
class ReferralTransactionUpdateView(GenericCRUDUpdateView): model = ReferralTransaction; page_key = "referral_transaction_crud"; list_url_name = "admindashboardx:referral_transaction_crud"; form_title = "Редактировать ReferralTransaction"
class ReferralTransactionDeleteView(GenericCRUDDeleteView): model = ReferralTransaction; page_key = "referral_transaction_crud"; list_url_name = "admindashboardx:referral_transaction_crud"

class ReferralSpecialOfferCRUDListView(GenericCRUDListView):
    model = ReferralSpecialOffer; page_key = "referral_special_offer_crud"; page_title = "AdminDashboardX · ReferralSpecialOffer CRUD"
    list_fields = ("id", "especial_for_user", "level_1_percentage", "level_2_percentage", "level_3_percentage", "level_4_percentage", "level_5_percentage")
    reset_url_name = "admindashboardx:referral_special_offer_crud"; create_url_name = "admindashboardx:referral_special_offer_create"
    edit_url_name = "admindashboardx:referral_special_offer_update"; delete_url_name = "admindashboardx:referral_special_offer_delete"; item_label = "special offer"
class ReferralSpecialOfferCreateView(GenericCRUDCreateView): model = ReferralSpecialOffer; page_key = "referral_special_offer_crud"; list_url_name = "admindashboardx:referral_special_offer_crud"; form_title = "Создать ReferralSpecialOffer"
class ReferralSpecialOfferUpdateView(GenericCRUDUpdateView): model = ReferralSpecialOffer; page_key = "referral_special_offer_crud"; list_url_name = "admindashboardx:referral_special_offer_crud"; form_title = "Редактировать ReferralSpecialOffer"
class ReferralSpecialOfferDeleteView(GenericCRUDDeleteView): model = ReferralSpecialOffer; page_key = "referral_special_offer_crud"; list_url_name = "admindashboardx:referral_special_offer_crud"

class TelegramBotCRUDListView(GenericCRUDListView):
    model = TelegramBot; page_key = "telegram_bot_crud"; page_title = "AdminDashboardX · TelegramBot CRUD"
    list_fields = ("id", "username", "title", "created_at")
    search_fields = ("username", "title")
    reset_url_name = "admindashboardx:telegram_bot_crud"; create_url_name = "admindashboardx:telegram_bot_create"
    edit_url_name = "admindashboardx:telegram_bot_update"; delete_url_name = "admindashboardx:telegram_bot_delete"; item_label = "telegram bot"
class TelegramBotCreateView(GenericCRUDCreateView): model = TelegramBot; page_key = "telegram_bot_crud"; list_url_name = "admindashboardx:telegram_bot_crud"; form_title = "Создать TelegramBot"
class TelegramBotUpdateView(GenericCRUDUpdateView): model = TelegramBot; page_key = "telegram_bot_crud"; list_url_name = "admindashboardx:telegram_bot_crud"; form_title = "Редактировать TelegramBot"
class TelegramBotDeleteView(GenericCRUDDeleteView): model = TelegramBot; page_key = "telegram_bot_crud"; list_url_name = "admindashboardx:telegram_bot_crud"

class TransactionCRUDListView(GenericCRUDListView):
    model = Transaction; page_key = "transaction_crud"; page_title = "AdminDashboardX · Transaction CRUD"
    list_fields = ("id", "user", "amount", "currency", "status", "payment_system", "payment_id")
    search_fields = ("payment_id", "description")
    reset_url_name = "admindashboardx:transaction_crud"; create_url_name = "admindashboardx:transaction_create"
    edit_url_name = "admindashboardx:transaction_update"; delete_url_name = "admindashboardx:transaction_delete"; item_label = "transaction"
class TransactionCreateView(GenericCRUDCreateView): model = Transaction; page_key = "transaction_crud"; list_url_name = "admindashboardx:transaction_crud"; form_title = "Создать Transaction"
class TransactionUpdateView(GenericCRUDUpdateView): model = Transaction; page_key = "transaction_crud"; list_url_name = "admindashboardx:transaction_crud"; form_title = "Редактировать Transaction"
class TransactionDeleteView(GenericCRUDDeleteView): model = Transaction; page_key = "transaction_crud"; list_url_name = "admindashboardx:transaction_crud"
