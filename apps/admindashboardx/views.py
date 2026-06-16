from collections import defaultdict
import csv
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from decimal import Decimal
from math import sqrt

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.conf import settings
from django.core.cache import cache
from django import forms
from django.forms import modelform_factory
from django.core.paginator import Paginator
from django.db.models import Case, Count, DecimalField, F, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDay, TruncWeek
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from openpyxl import Workbook

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
from .manual_tasks import MANUAL_TASKS
from .models import ManualTaskRun, ManualTaskLog

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

    _SUCCESS_PAYMENT_Q = Q(paid=True) | Q(status="succeeded")

    @classmethod
    def _build_payload(cls):
        now = timezone.now()
        today = timezone.localdate()

        pay_ok = Transaction.objects.filter(cls._SUCCESS_PAYMENT_Q).exclude(side="Вывод средств")
        amt_field = Transaction._meta.get_field("amount")
        zero_money = Value(Decimal("0"), output_field=amt_field)
        rev_row = pay_ok.aggregate(
            revenue_day=Sum(
                Case(When(timestamp__date=today, then=F("amount")), default=zero_money, output_field=amt_field)
            ),
            revenue_month=Sum(
                Case(
                    When(Q(timestamp__year=today.year, timestamp__month=today.month), then=F("amount")),
                    default=zero_money,
                    output_field=amt_field,
                )
            ),
            revenue_year=Sum(
                Case(When(timestamp__year=today.year, then=F("amount")), default=zero_money, output_field=amt_field)
            ),
        )
        revenue_day = rev_row["revenue_day"] or Decimal("0")
        revenue_month = rev_row["revenue_month"] or Decimal("0")
        revenue_year = rev_row["revenue_year"] or Decimal("0")

        income_row = IncomeInfo.objects.only("total_amount").order_by("-pk").first()
        revenue_project_total = (
            income_row.total_amount if income_row and income_row.total_amount is not None else Decimal("0")
        )

        users_row = TelegramUser.objects.aggregate(
            users_total=Count("id"),
            users_month=Count(
                Case(
                    When(Q(join_date__year=today.year, join_date__month=today.month), then=Value(1)),
                    output_field=IntegerField(),
                )
            ),
            users_day=Count(Case(When(join_date=today, then=Value(1)), output_field=IntegerField())),
        )

        tx_row = Transaction.objects.aggregate(
            tx_count_total=Count("id"),
            tx_count_month=Count(
                Case(
                    When(Q(timestamp__year=today.year, timestamp__month=today.month), then=Value(1)),
                    output_field=IntegerField(),
                )
            ),
            tx_count_day=Count(Case(When(timestamp__date=today, then=Value(1)), output_field=IntegerField())),
        )

        wd_row = WithdrawalRequest.objects.aggregate(
            wd_count_total=Count("id"),
            wd_count_month=Count(
                Case(
                    When(
                        Q(timestamp__isnull=False)
                        & Q(timestamp__year=today.year, timestamp__month=today.month),
                        then=Value(1),
                    ),
                    output_field=IntegerField(),
                )
            ),
            wd_count_day=Count(
                Case(
                    When(Q(timestamp__isnull=False) & Q(timestamp__date=today), then=Value(1)),
                    output_field=IntegerField(),
                )
            ),
        )

        error_levels = ("WARNING", "FATAL")
        period_days = 30
        since = now - timedelta(days=period_days)
        kpi_error_logs = Logging.objects.filter(datetime__gte=since, log_level__in=error_levels).count()

        bot_activity_q = (
            Q(category="bot")
            | (
                Q(category="vpn")
                & Q(message__icontains="[BOT]")
                & ~Q(message__icontains="[CELERY]")
            )
            | (
                Q(category="payment")
                & Q(message__icontains="[BOT]")
                & ~Q(message__icontains="[CELERY]")
            )
        )
        log_today = Logging.objects.filter(datetime__date=today, user_id__isnull=False)
        ids_site = set(log_today.filter(category="web").values_list("user_id", flat=True).distinct())
        ids_bot = set(log_today.filter(bot_activity_q).values_list("user_id", flat=True).distinct())
        activity_users_site = len(ids_site)
        activity_users_bot = len(ids_bot)
        activity_users_day = len(ids_site | ids_bot)

        _months_ru = (
            "",
            "январь",
            "февраль",
            "март",
            "апрель",
            "май",
            "июнь",
            "июль",
            "август",
            "сентябрь",
            "октябрь",
            "ноябрь",
            "декабрь",
        )
        stats_month_label = f"{_months_ru[today.month]} {today.year}"
        stats_day_label = today.strftime("%d.%m.%Y")

        return {
            "stats_year": today.year,
            "stats_month": stats_month_label,
            "stats_day": stats_day_label,
            "period_days": period_days,
            "kpi_error_logs": kpi_error_logs,
            "revenue_project_total": float(revenue_project_total),
            "revenue_year": float(revenue_year),
            "revenue_month": float(revenue_month),
            "revenue_day": float(revenue_day),
            "users_total": users_row["users_total"],
            "users_month": users_row["users_month"],
            "users_day": users_row["users_day"],
            "tx_count_total": tx_row["tx_count_total"],
            "tx_count_month": tx_row["tx_count_month"],
            "tx_count_day": tx_row["tx_count_day"],
            "wd_count_total": wd_row["wd_count_total"],
            "wd_count_month": wd_row["wd_count_month"],
            "wd_count_day": wd_row["wd_count_day"],
            "activity_users_day": activity_users_day,
            "activity_users_site": activity_users_site,
            "activity_users_bot": activity_users_bot,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                **self._base_context(),
                "period_days": 30,
            }
        )
        return context


class AdminDashboardIndexDataView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Главная"
    page_key = "index"

    def get(self, request, *args, **kwargs):
        cache_key = "admx:index:data:v5"
        payload = cache.get(cache_key)
        if payload is None:
            payload = AdminDashboardIndexView._build_payload()
            cache.set(cache_key, payload, 60)
        return JsonResponse(payload)

def _admx_pearson_corr(xs, ys):
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / sqrt(var_x * var_y)


def _admx_best_lag_corr(rev_series, usr_series, max_lag=7):
    """Максимум |corr| между доходом и регистрациями при сдвиге 0..max_lag (доход позже на lag дней)."""
    best_lag, best_r = 0, None
    for lag in range(0, max_lag + 1):
        xs, ys = (rev_series, usr_series) if lag == 0 else (rev_series[lag:], usr_series[:-lag])
        if len(xs) < 3:
            continue
        r = _admx_pearson_corr(xs, ys)
        if r is None:
            continue
        if best_r is None or abs(r) > abs(best_r):
            best_r = r
            best_lag = lag
    return best_lag, best_r


def _admx_autodebit_payment_q():
    """RoboKassa: дочерний рекуррент; прочие ПС: пометка в описании (напр. ЮKassa Celery)."""
    return (
        Q(robokassa_recurring_previous_inv_id__isnull=False)
        & ~Q(robokassa_recurring_previous_inv_id="")
    ) | Q(description__icontains="рекуррент")


def _admx_corr_strength_label(r):
    if r is None:
        return None
    a = abs(r)
    if a < 0.2:
        return "слабая"
    if a < 0.5:
        return "умеренная"
    return "сильная"


def _admx_build_revenue_insights(
    *,
    series_daily,
    rev_series,
    usr_series,
    corr_daily,
    revenue_period,
    payments_period_n,
    autodebit_n,
    autodebit_revenue,
    conversion_all_pct,
    cohort_conversion_pct,
    new_users_period,
    by_ps,
    payment_related_logs_n,
):
    bullets = []

    if corr_daily is not None:
        strength = _admx_corr_strength_label(corr_daily)
        bullets.append(
            f"За выбранное окно связь «доход ↔ новые пользователи» по дням {strength or '—'} "
            f"(корреляция Пирсона ≈ {corr_daily:.3f}); это не доказывает причинность."
        )

    max_lag = min(7, max(0, len(rev_series) - 3))
    lag, lag_r = _admx_best_lag_corr(rev_series, usr_series, max_lag=max_lag)
    if lag_r is not None and lag > 0 and abs(lag_r) >= 0.25:
        bullets.append(
            f"При сдвиге на {lag} дн. (доход позже регистраций) корреляция доходит до ≈ {lag_r:.3f} — возможна отложенная оплата после регистрации."
        )


    n_days = len(series_daily)

    if len(rev_series) >= 14:
        tail = 7
        a = sum(rev_series[-tail:]) / tail
        b = sum(rev_series[-2 * tail : -tail]) / tail
        if b > 0:
            bullets.append(
                f"Средний дневной доход: последние {tail} дн. ≈ {a:.0f} ₽/день, предыдущие {tail} дн. ≈ {b:.0f} ₽/день ({((a - b) / b * 100):+.1f}%)."
            )

    delta = float(cohort_conversion_pct - conversion_all_pct)
    if new_users_period > 0 and abs(delta) >= 8:
        if delta > 0:
            bullets.append(
                "Когорта текущего окна конвертируется заметно выше среднего по базе — возможен приток качественного трафика или акции."
            )
        else:
            bullets.append(
                "Когорта окна конвертируется ниже среднего по базе — имеет смысл проверить источники трафика и онбординг."
            )

    elif payment_related_logs_n >= 5:
        bullets.append(f"В логах за период {payment_related_logs_n} записей WARNING/FATAL по категории «Платежи».")

    if not bullets:
        bullets.append(
            "Недостаточно данных или выраженных паттернов для коротких выводов — расширьте окно дней или проверьте разрезы по ПС."
        )

    return bullets[:12]


def _admx_payment_system_labels():
    return dict(Transaction._meta.get_field("payment_system").choices)


def _admx_parse_optional_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


class RevenueAnalyticsView(DashboardBaseView):
    """Доходы, пользователи, конверсия, автосписания (несколько ПС), платёжные системы, ошибки — по окну дней."""

    template_name = "admindashboardx/revenue_analytics.html"
    page_title = "AdminDashboardX · Аналитика доходов"
    page_key = "revenue_analytics"

    _INCOMING_OK = (Q(paid=True) | Q(status="succeeded"))

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _parse_range_days(raw_value):
        raw_days = (raw_value or "90").strip()
        try:
            range_days = int(raw_days)
        except ValueError:
            range_days = 90
        return max(7, min(range_days, 730))

    @staticmethod
    def _parse_payment_system(raw_value):
        return (raw_value or "").strip()

    @staticmethod
    def _parse_autodebit_mode(raw_value):
        mode = (raw_value or "all").strip().lower()
        return mode if mode in ("all", "only", "exclude") else "all"

    @classmethod
    def _build_payload(cls, range_days, payment_system="", autodebit_mode="all"):
        now = timezone.now()
        start_dt = now - timedelta(days=range_days)
        prev_start_dt = start_dt - timedelta(days=range_days)
        tz = timezone.get_current_timezone()
        start_date = timezone.localtime(start_dt).date()
        prev_start_date = timezone.localtime(prev_start_dt).date()
        prev_end_date = start_date - timedelta(days=1)
        today = timezone.localdate()

        ps_labels = _admx_payment_system_labels()

        def ps_display(code):
            if not code:
                return "—"
            return ps_labels.get(str(code), str(code))

        incoming_base = Transaction.objects.filter(cls._INCOMING_OK, timestamp__gte=start_dt)
        if payment_system:
            incoming_base = incoming_base.filter(payment_system=payment_system)
        autodebit_q = _admx_autodebit_payment_q()
        if autodebit_mode == "only":
            incoming_base = incoming_base.filter(autodebit_q)
        elif autodebit_mode == "exclude":
            incoming_base = incoming_base.exclude(autodebit_q)

        prev_incoming_base = Transaction.objects.filter(
            cls._INCOMING_OK,
            timestamp__gte=prev_start_dt,
            timestamp__lt=start_dt,
        )
        if payment_system:
            prev_incoming_base = prev_incoming_base.filter(payment_system=payment_system)
        if autodebit_mode == "only":
            prev_incoming_base = prev_incoming_base.filter(autodebit_q)
        elif autodebit_mode == "exclude":
            prev_incoming_base = prev_incoming_base.exclude(autodebit_q)

        agg_pay_by_day = (
            incoming_base.annotate(period=TruncDay("timestamp", tzinfo=tz))
            .values("period")
            .annotate(revenue=Sum("amount"), payments_n=Count("id"))
        )
        pay_map = {}
        for row in agg_pay_by_day:
            pd = row["period"]
            dkey = pd.date() if hasattr(pd, "date") else pd
            pay_map[dkey] = {
                "revenue": row["revenue"] or Decimal("0"),
                "payments_n": row["payments_n"],
            }

        user_rows = (
            TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today)
            .values("join_date")
            .annotate(new_users=Count("id"))
        )
        user_map = {r["join_date"]: r["new_users"] for r in user_rows}

        series_daily = []
        d = start_date
        rev_series = []
        usr_series = []
        while d <= today:
            p = pay_map.get(d)
            rev = float(p["revenue"]) if p else 0.0
            nu = int(user_map.get(d, 0))
            series_daily.append(
                {
                    "date": d.isoformat(),
                    "date_short": d.strftime("%d.%m"),
                    "revenue": rev,
                    "new_users": nu,
                    "payments_n": int(p["payments_n"]) if p else 0,
                }
            )
            rev_series.append(rev)
            usr_series.append(float(nu))
            d += timedelta(days=1)

        revenue_period = incoming_base.aggregate(t=Sum("amount")).get("t") or Decimal("0")
        payments_period_n = incoming_base.count()

        new_users_period = TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today).count()
        prev_new_users_period = TelegramUser.objects.filter(
            join_date__gte=prev_start_date,
            join_date__lte=prev_end_date,
        ).count()
        users_total = TelegramUser.objects.count()
        paying_users_all = (
            Transaction.objects.filter(cls._INCOMING_OK).exclude(user_id__isnull=True).values("user_id").distinct().count()
        )
        conversion_all_pct = (Decimal(paying_users_all) / Decimal(users_total) * 100) if users_total else Decimal("0")

        cohort_users_qs = TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today)
        new_ids_count = cohort_users_qs.count()
        paid_among_new = (
            Transaction.objects.filter(cls._INCOMING_OK, user_id__in=cohort_users_qs.values_list("id", flat=True))
            .values("user_id")
            .distinct()
            .count()
            if new_ids_count
            else 0
        )
        cohort_conversion_pct = (
            (Decimal(paid_among_new) / Decimal(new_ids_count) * 100) if new_ids_count else Decimal("0")
        )

        payers_period = incoming_base.exclude(user_id__isnull=True).values("user_id").distinct().count()
        arpu_period = (revenue_period / Decimal(payers_period)) if payers_period else Decimal("0")
        prev_revenue_period = prev_incoming_base.aggregate(t=Sum("amount")).get("t") or Decimal("0")
        prev_payments_period_n = prev_incoming_base.count()
        prev_payers_period = prev_incoming_base.exclude(user_id__isnull=True).values("user_id").distinct().count()
        prev_arpu_period = (prev_revenue_period / Decimal(prev_payers_period)) if prev_payers_period else Decimal("0")

        corr_daily = _admx_pearson_corr(rev_series, usr_series)

        by_ps = []
        ps_agg = (
            incoming_base.values("payment_system")
            .annotate(revenue=Sum("amount"), ok_n=Count("id"))
            .order_by("-revenue")
        )
        failed_qs = Transaction.objects.filter(
            timestamp__gte=start_dt,
            status__in=("failed", "canceled"),
        ).exclude(side="Вывод средств")
        failed_by_ps = {r["payment_system"]: r["fn"] for r in failed_qs.values("payment_system").annotate(fn=Count("id"))}
        pending_by_ps = {
            r["payment_system"]: r["pn"]
            for r in Transaction.objects.filter(timestamp__gte=start_dt, status="pending")
            .exclude(side="Вывод средств")
            .values("payment_system")
            .annotate(pn=Count("id"))
        }

        rev_other_chart = []
        ps_chart_colors = []
        palette = ["#7c9cff", "#6fd3a9", "#f0ad4e", "#e06666", "#b794f6", "#5bc0de", "#ffd066"]
        pi = 0
        for row in ps_agg:
            ps_code = row["payment_system"]
            lab = ps_display(ps_code)
            rev_v = float(row["revenue"] or 0)
            ok_n = row["ok_n"]
            fn = failed_by_ps.get(ps_code, 0)
            pn = pending_by_ps.get(ps_code, 0)
            tot_attempts = ok_n + fn + pn
            success_rate = (ok_n / tot_attempts * 100) if tot_attempts else None
            by_ps.append(
                {
                    "payment_system": ps_code or "",
                    "label": lab,
                    "revenue": row["revenue"] or Decimal("0"),
                    "ok_count": ok_n,
                    "failed_count": fn,
                    "pending_count": pn,
                    "success_rate": success_rate,
                }
            )
            rev_other_chart.append({"label": lab, "value": rev_v})
            ps_chart_colors.append(palette[pi % len(palette)])
            pi += 1

        positive_tx_by_day = (
            incoming_base.exclude(side="Вывод средств")
            .annotate(period=TruncDay("timestamp", tzinfo=tz))
            .values("period")
            .annotate(tx_n=Count("id"))
        )
        positive_tx_map = {}
        for row in positive_tx_by_day:
            pd = row["period"]
            dkey = pd.date() if hasattr(pd, "date") else pd
            positive_tx_map[dkey] = int(row["tx_n"] or 0)

        users_tx_series = []
        for item in series_daily:
            dkey = datetime.strptime(item["date"], "%Y-%m-%d").date()
            tx_n = positive_tx_map.get(dkey, 0)
            users_n = int(item["new_users"])
            users_tx_series.append(
                {
                    "date_short": item["date_short"],
                    "new_users": users_n,
                    "positive_tx_n": tx_n,
                    "users_per_positive_tx": (users_n / tx_n) if tx_n else None,
                }
            )

        autodebit_qs = incoming_base.filter(autodebit_q)
        autodebit_n = autodebit_qs.count()
        autodebit_revenue = autodebit_qs.aggregate(t=Sum("amount")).get("t") or Decimal("0")
        recurring_by_ps = []
        for row in autodebit_qs.values("payment_system").annotate(n=Count("id"), rev=Sum("amount")).order_by("-rev"):
            recurring_by_ps.append(
                {
                    "label": ps_display(row["payment_system"]),
                    "count": row["n"],
                    "revenue": row["rev"] or Decimal("0"),
                }
            )

        cat_labels = dict(Logging._meta.get_field("category").choices)
        log_issues = []
        for row in (
            Logging.objects.filter(datetime__gte=start_dt, log_level__in=("WARNING", "FATAL"))
            .values("log_level", "category")
            .annotate(n=Count("id"))
            .order_by("-n")[:25]
        ):
            cat_key = row["category"]
            log_issues.append(
                {
                    "level": row["log_level"],
                    "category": cat_key,
                    "category_label": cat_labels.get(cat_key, cat_key),
                    "n": row["n"],
                }
            )

        payment_related_logs_n = Logging.objects.filter(
            datetime__gte=start_dt,
            log_level__in=("WARNING", "FATAL"),
            category="payment",
        ).count()

        prev_payment_related_logs_n = Logging.objects.filter(
            datetime__gte=prev_start_dt,
            datetime__lt=start_dt,
            log_level__in=("WARNING", "FATAL"),
            category="payment",
        ).count()

        revenue_insights = _admx_build_revenue_insights(
            series_daily=series_daily,
            rev_series=rev_series,
            usr_series=usr_series,
            corr_daily=corr_daily,
            revenue_period=revenue_period,
            payments_period_n=payments_period_n,
            autodebit_n=autodebit_n,
            autodebit_revenue=autodebit_revenue,
            conversion_all_pct=conversion_all_pct,
            cohort_conversion_pct=cohort_conversion_pct,
            new_users_period=new_users_period,
            by_ps=by_ps,
            payment_related_logs_n=payment_related_logs_n,
        )

        income_row = IncomeInfo.objects.order_by("-pk").first()
        income_snapshot = income_row.total_amount if income_row and income_row.total_amount is not None else Decimal("0")

        # Ожидаемый рекуррент на завтра: сегодня последний день подписки, автосписание не отменено, подписка активна.
        amt_field = Transaction._meta.get_field("amount")
        zero_money = Value(Decimal("0"), output_field=amt_field)
        last_success_amount_sq = (
            Transaction.objects.filter(
                cls._INCOMING_OK,
                user_id=OuterRef("pk"),
            )
            .exclude(side="Вывод средств")
            .order_by("-timestamp", "-id")
            .values("amount")[:1]
        )
        exp_recurring_row = (
            TelegramUser.objects.filter(
                subscription_expiration=today,
                permission_revoked=False,
                subscription_status=True,
            )
            .annotate(
                last_success_amount=Coalesce(
                    Subquery(last_success_amount_sq, output_field=amt_field),
                    zero_money,
                )
            )
            .aggregate(
                expected_recurring_tomorrow_n=Count("id"),
                expected_recurring_tomorrow_revenue=Sum("last_success_amount"),
            )
        )
        expected_recurring_tomorrow_n = exp_recurring_row["expected_recurring_tomorrow_n"] or 0
        expected_recurring_tomorrow_revenue = (
            exp_recurring_row["expected_recurring_tomorrow_revenue"] or Decimal("0")
        )

        # Истекшая подписка, но есть платёжный метод и разрешение на списание не отозвано.
        expired_paymethod_row = (
            TelegramUser.objects.filter(
                subscription_expiration__lt=today,
                permission_revoked=False,
            )
            .exclude(Q(payment_method_id__isnull=True) | Q(payment_method_id=""))
            .annotate(
                last_success_amount=Coalesce(
                    Subquery(last_success_amount_sq, output_field=amt_field),
                    zero_money,
                )
            )
            .aggregate(
                expired_sub_paymethod_not_revoked_n=Count("id"),
                expired_sub_paymethod_not_revoked_revenue=Sum("last_success_amount"),
            )
        )
        expired_sub_paymethod_not_revoked_n = expired_paymethod_row["expired_sub_paymethod_not_revoked_n"] or 0
        expired_sub_paymethod_not_revoked_revenue = (
            expired_paymethod_row["expired_sub_paymethod_not_revoked_revenue"] or Decimal("0")
        )

        failed_recent_qs = (
            Transaction.objects.filter(timestamp__gte=start_dt, status__in=("failed", "canceled"))
            .exclude(side="Вывод средств")
            .order_by("-timestamp")[:30]
        )
        failed_recent = [
            {
                "id": tx.id,
                "timestamp": timezone.localtime(tx.timestamp).strftime("%d.%m.%Y %H:%M") if tx.timestamp else "—",
                "amount": float(tx.amount or 0),
                "currency": tx.currency or "RUB",
                "payment_system": tx.payment_system or "—",
                "status": tx.status or "—",
            }
            for tx in failed_recent_qs
        ]

        chart_daily_payload = {
            "labels": [x["date_short"] for x in series_daily],
            "revenue": [x["revenue"] for x in series_daily],
            "new_users": [x["new_users"] for x in series_daily],
            "payments_n": [x["payments_n"] for x in series_daily],
        }

        def pct_delta(cur, prev):
            cur = float(cur or 0)
            prev = float(prev or 0)
            if prev == 0:
                return None
            return (cur - prev) / prev * 100.0

        kpi_deltas = {
            "revenue_period_pct": pct_delta(revenue_period, prev_revenue_period),
            "payments_period_n_pct": pct_delta(payments_period_n, prev_payments_period_n),
            "new_users_period_pct": pct_delta(new_users_period, prev_new_users_period),
            "payers_period_pct": pct_delta(payers_period, prev_payers_period),
            "arpu_period_pct": pct_delta(arpu_period, prev_arpu_period),
            "payment_related_logs_n_pct": pct_delta(payment_related_logs_n, prev_payment_related_logs_n),
        }

        tx_list_url = reverse("admindashboardx:transactions")
        logs_list_url = reverse("admindashboardx:logs")
        rev_analytics_url = reverse("admindashboardx:revenue_analytics")
        funnel_url = reverse("admindashboardx:funnel_analytics")
        dcf = start_date.isoformat()
        dct = today.isoformat()
        period_tx_qs = urlencode({"date_from": dcf, "date_to": dct})

        alerts = []
        if kpi_deltas["revenue_period_pct"] is not None and kpi_deltas["revenue_period_pct"] <= -20:
            alerts.append(
                {
                    "level": "critical",
                    "title": "Сильная просадка дохода",
                    "message": f"Доход ниже прошлого периода на {abs(kpi_deltas['revenue_period_pct']):.1f}%.",
                    "actions": [
                        {"label": "Транзакции за период", "url": f"{tx_list_url}?{period_tx_qs}"},
                        {"label": "Аналитика доходов", "url": f"{rev_analytics_url}?{urlencode({'days': range_days})}"},
                    ],
                }
            )
        if payment_related_logs_n >= 20:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Рост ошибок в платежах",
                    "message": f"За окно зафиксировано {payment_related_logs_n} WARNING/FATAL по категории payment.",
                    "actions": [
                        {
                            "label": "Логи (WARNING)",
                            "url": f"{logs_list_url}?{urlencode({'date_from': dcf, 'date_to': dct, 'level': 'WARNING'})}",
                        },
                        {
                            "label": "Логи (FATAL)",
                            "url": f"{logs_list_url}?{urlencode({'date_from': dcf, 'date_to': dct, 'level': 'FATAL'})}",
                        },
                    ],
                }
            )
        total_failed = sum(int(x["failed_count"]) for x in by_ps)
        total_ok = sum(int(x["ok_count"]) for x in by_ps)



        if total_ok + total_failed >= 20:
            fail_rate = (total_failed / (total_ok + total_failed)) * 100
            if fail_rate >= 15:
                alerts.append(
                    {
                        "level": "warning",
                        "title": "Высокая доля неуспешных платежей",
                        "message": f"Failed/canceled составляет {fail_rate:.1f}% от завершенных попыток.",
                        "actions": [
                            {
                                "label": "Failed",
                                "url": f"{tx_list_url}?{urlencode({'date_from': dcf, 'date_to': dct, 'status': 'failed'})}",
                            },
                            {
                                "label": "Canceled",
                                "url": f"{tx_list_url}?{urlencode({'date_from': dcf, 'date_to': dct, 'status': 'canceled'})}",
                            },
                            {"label": "Все за период", "url": f"{tx_list_url}?{period_tx_qs}"},
                        ],
                    }
                )
        if not alerts:
            alerts.append(
                {
                    "level": "ok",
                    "title": "Критичных аномалий не найдено",
                    "message": "Метрики в ожидаемых пределах.",
                    "actions": [
                        {"label": "Транзакции", "url": tx_list_url},
                        {"label": "Воронка", "url": funnel_url},
                    ],
                }
            )

        return {
            "range_days": range_days,
            "period_days": range_days,
            "period_start": start_date.strftime("%d.%m.%Y"),
            "period_end": today.strftime("%d.%m.%Y"),
            "days_choices": (30, 90, 180, 365),
            "selected_payment_system": payment_system,
            "selected_autodebit_mode": autodebit_mode,
            "available_payment_systems": [
                {"value": str(k), "label": v}
                for k, v in sorted(ps_labels.items(), key=lambda item: item[1])
                if k
            ],
            "kpis": {
                "revenue_period": float(revenue_period),
                "payments_period_n": payments_period_n,
                "new_users_period": new_users_period,
                "payers_period": payers_period,
                "arpu_period": float(arpu_period),
                "conversion_all_pct": float(conversion_all_pct),
                "cohort_conversion_pct": float(cohort_conversion_pct),
                "paid_among_new": paid_among_new,
                "paying_users_all": paying_users_all,
                "users_total": users_total,
                "income_snapshot": float(income_snapshot),
                "autodebit_n": autodebit_n,
                "autodebit_revenue": float(autodebit_revenue),
                "payment_related_logs_n": payment_related_logs_n,
                "expected_recurring_tomorrow_n": expected_recurring_tomorrow_n,
                "expected_recurring_tomorrow_revenue": float(expected_recurring_tomorrow_revenue),
                "expired_sub_paymethod_not_revoked_n": expired_sub_paymethod_not_revoked_n,
                "expired_sub_paymethod_not_revoked_revenue": float(expired_sub_paymethod_not_revoked_revenue),
            },
            "kpi_deltas": kpi_deltas,
            "prev_period": {
                "period_start": prev_start_date.strftime("%d.%m.%Y"),
                "period_end": prev_end_date.strftime("%d.%m.%Y"),
                "revenue_period": float(prev_revenue_period),
                "payments_period_n": prev_payments_period_n,
                "new_users_period": prev_new_users_period,
                "payers_period": prev_payers_period,
                "arpu_period": float(prev_arpu_period),
                "payment_related_logs_n": prev_payment_related_logs_n,
            },
            "alerts": alerts,
            "revenue_insights": revenue_insights,
            "by_payment_system": [{**row, "revenue": float(row["revenue"])} for row in by_ps],
            "recurring_by_ps": [{**row, "revenue": float(row["revenue"])} for row in recurring_by_ps],
            "log_issues": log_issues,
            "failed_recent": failed_recent,
            "charts": {
                "daily": chart_daily_payload,
                "payment_system_revenue": {
                    "labels": [x["label"] for x in rev_other_chart],
                    "values": [x["value"] for x in rev_other_chart],
                    "colors": ps_chart_colors,
                },
                "users_vs_positive_tx": {
                    "labels": [x["date_short"] for x in users_tx_series],
                    "new_users": [x["new_users"] for x in users_tx_series],
                    "positive_tx_n": [x["positive_tx_n"] for x in users_tx_series],
                    "users_per_positive_tx": [x["users_per_positive_tx"] for x in users_tx_series],
                },
            },
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        range_days = self._parse_range_days(self.request.GET.get("days"))
        payment_system = self._parse_payment_system(self.request.GET.get("payment_system"))
        autodebit_mode = self._parse_autodebit_mode(self.request.GET.get("autodebit_mode"))
        ps_labels = _admx_payment_system_labels()
        context.update(
            {
                **self._base_context(),
                "range_days": range_days,
                "period_days": range_days,
                "days_choices": (30, 90, 180, 365),
                "selected_payment_system": payment_system,
                "selected_autodebit_mode": autodebit_mode,
                "available_payment_systems": [
                    {"value": str(k), "label": v}
                    for k, v in sorted(ps_labels.items(), key=lambda item: item[1])
                    if k
                ],
            }
        )
        return context


class RevenueAnalyticsDataView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Аналитика доходов"
    page_key = "revenue_analytics"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return JsonResponse({"detail": "forbidden"}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        range_days = RevenueAnalyticsView._parse_range_days(request.GET.get("days"))
        payment_system = RevenueAnalyticsView._parse_payment_system(request.GET.get("payment_system"))
        autodebit_mode = RevenueAnalyticsView._parse_autodebit_mode(request.GET.get("autodebit_mode"))
        cache_key = f"admx:revenue:data:v3:{range_days}:{payment_system or 'all'}:{autodebit_mode}"
        payload = cache.get(cache_key)
        if payload is None:
            payload = RevenueAnalyticsView._build_payload(
                range_days=range_days,
                payment_system=payment_system,
                autodebit_mode=autodebit_mode,
            )
            cache.set(cache_key, payload, 90)
        return JsonResponse(payload)


class RevenueAnalyticsExportCsvView(DashboardBaseView, View):
    page_title = "AdminDashboardX · Аналитика доходов CSV"
    page_key = "revenue_analytics"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return JsonResponse({"detail": "forbidden"}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        range_days = RevenueAnalyticsView._parse_range_days(request.GET.get("days"))
        payment_system = RevenueAnalyticsView._parse_payment_system(request.GET.get("payment_system"))
        autodebit_mode = RevenueAnalyticsView._parse_autodebit_mode(request.GET.get("autodebit_mode"))
        payload = RevenueAnalyticsView._build_payload(
            range_days=range_days,
            payment_system=payment_system,
            autodebit_mode=autodebit_mode,
        )

        now_str = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="revenue_analytics_{now_str}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)

        writer.writerow(["Параметр", "Значение"])
        writer.writerow(["Период", f"{payload['period_start']} - {payload['period_end']}"])
        writer.writerow(["Дней", payload["range_days"]])
        writer.writerow(["Payment system", payload.get("selected_payment_system") or "all"])
        writer.writerow(["Autodebit mode", payload.get("selected_autodebit_mode") or "all"])
        writer.writerow([])
        writer.writerow(["KPI", "Текущее окно", "Предыдущее окно", "Delta %"])
        prev = payload.get("prev_period") or {}
        deltas = payload.get("kpi_deltas") or {}
        kpi = payload.get("kpis") or {}
        rows = [
            ("Доход за период", kpi.get("revenue_period"), prev.get("revenue_period"), deltas.get("revenue_period_pct")),
            ("Успешных платежей", kpi.get("payments_period_n"), prev.get("payments_period_n"), deltas.get("payments_period_n_pct")),
            ("Новых пользователей", kpi.get("new_users_period"), prev.get("new_users_period"), deltas.get("new_users_period_pct")),
            ("Плативших пользователей", kpi.get("payers_period"), prev.get("payers_period"), deltas.get("payers_period_pct")),
            ("ARPU", kpi.get("arpu_period"), prev.get("arpu_period"), deltas.get("arpu_period_pct")),
            ("Payment warning/fatal logs", kpi.get("payment_related_logs_n"), prev.get("payment_related_logs_n"), deltas.get("payment_related_logs_n_pct")),
        ]
        for title, cur, prv, dlt in rows:
            writer.writerow([title, cur, prv, "" if dlt is None else round(float(dlt), 2)])
        writer.writerow([])
        writer.writerow(
            [
                "Рекуррент на завтра (оценка): пользователей",
                kpi.get("expected_recurring_tomorrow_n"),
                "",
                "",
            ]
        )
        writer.writerow(
            [
                "Рекуррент на завтра (оценка): сумма по последним успешным платежам, ₽",
                kpi.get("expected_recurring_tomorrow_revenue"),
                "",
                "",
            ]
        )
        writer.writerow(
            [
                "Истекшая подписка + метод оплаты + не отозвано списание: пользователей",
                kpi.get("expired_sub_paymethod_not_revoked_n"),
                "",
                "",
            ]
        )
        writer.writerow(
            [
                "Истекшая подписка + метод оплаты + не отозвано: сумма последних успешных платежей, ₽",
                kpi.get("expired_sub_paymethod_not_revoked_revenue"),
                "",
                "",
            ]
        )
        writer.writerow([])
        writer.writerow(["Дата", "Доход", "Новые пользователи", "Успешных платежей"])
        daily = (payload.get("charts") or {}).get("daily") or {}
        labels = daily.get("labels") or []
        rev = daily.get("revenue") or []
        users = daily.get("new_users") or []
        payments = daily.get("payments_n") or []
        for i, label in enumerate(labels):
            writer.writerow([label, rev[i] if i < len(rev) else "", users[i] if i < len(users) else "", payments[i] if i < len(payments) else ""])

        return response


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


class UserAnalyticsExcelExportView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Агрегаты по всем TelegramUser (pk = id в БД).
    Дата когорты: User.date_joined (дата), если есть UserProfile и Django User; иначе TelegramUser.join_date.
    Исключаются только те TelegramUser, у кого связанный через профиль User — staff или superuser.
    Конверсия: % когорты с ≥1 успешной транзакцией (paid=True OR status='succeeded').
    """

    login_url = "login"
    raise_exception = True

    SUCCESS_Q = Q(paid=True) | Q(status="succeeded")

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        paid_tg_pks = set(
            Transaction.objects.filter(self.SUCCESS_Q)
            .exclude(user_id__isnull=True)
            .values_list("user_id", flat=True)
            .distinct()
        )

        profile_by_tg_id = {}
        for p in UserProfile.objects.select_related("user").exclude(telegram_user_id__isnull=True).iterator(
            chunk_size=4096
        ):
            profile_by_tg_id[p.telegram_user_id] = p

        daily_buckets = defaultdict(list)
        monthly_buckets = defaultdict(list)
        yearly_buckets = defaultdict(list)

        for tg in TelegramUser.objects.only("id", "join_date").iterator(chunk_size=4096):
            profile = profile_by_tg_id.get(tg.id)
            if profile is not None:
                user = profile.user
                if user.is_staff or user.is_superuser:
                    continue
                dj = user.date_joined
                if dj:
                    day = dj.date() if hasattr(dj, "date") else dj
                else:
                    day = tg.join_date
            else:
                day = tg.join_date

            if not day:
                continue

            pk = tg.id
            daily_buckets[day].append(pk)
            monthly_buckets[(day.year, day.month)].append(pk)
            yearly_buckets[day.year].append(pk)

        def rows_for(bucket_map, key_display_fn):
            out = []
            for key in sorted(bucket_map.keys()):
                ids = bucket_map[key]
                n = len(ids)
                paid_n = sum(1 for pk in ids if pk in paid_tg_pks)
                conv = (paid_n / n) * 100 if n else 0.0
                out.append((key_display_fn(key), n, paid_n, conv))
            return out

        wb = Workbook()
        ws = wb.active
        ws.title = "User_Analytics"

        def append_section(title, data_rows):
            ws.append([title])
            ws.append(["period", "new_users", "with_successful_payment", "conversion_rate_%"])
            for period_label, n, paid_n, conv in data_rows:
                ws.append([period_label, n, paid_n, f"{conv:.2f}%"])
            ws.append([])

        append_section(
            "Daily (cohort date: User.date_joined if linked else TelegramUser.join_date)",
            rows_for(daily_buckets, lambda k: k.isoformat() if hasattr(k, "isoformat") else str(k)),
        )
        append_section(
            "Monthly",
            rows_for(monthly_buckets, lambda k: f"{k[0]:04d}-{k[1]:02d}"),
        )
        append_section(
            "Yearly",
            rows_for(yearly_buckets, lambda k: f"{k:04d}"),
        )

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        filename = f"user_analytics_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response


class TransactionsListView(DashboardBaseView):
    template_name = "admindashboardx/transactions.html"
    page_title = "AdminDashboardX · Транзакции"
    page_key = "transactions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        date_from_raw = (self.request.GET.get("date_from") or "").strip()
        date_to_raw = (self.request.GET.get("date_to") or "").strip()
        payment_system = (self.request.GET.get("payment_system") or "").strip()
        date_from = _admx_parse_optional_date(date_from_raw)
        date_to = _admx_parse_optional_date(date_to_raw)

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
        if payment_system:
            tx_qs = tx_qs.filter(payment_system=payment_system)
        if date_from:
            tx_qs = tx_qs.filter(timestamp__date__gte=date_from)
        if date_to:
            tx_qs = tx_qs.filter(timestamp__date__lte=date_to)

        ps_labels = _admx_payment_system_labels()
        payment_system_choices = [
            {"value": str(k), "label": v} for k, v in sorted(ps_labels.items(), key=lambda item: item[1]) if k
        ]

        context.update(
            {
                **self._base_context(),
                "tx_page": self._paginate(tx_qs, per_page=50),
                "q": query,
                "status": status,
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "payment_system": payment_system,
                "payment_system_choices": payment_system_choices,
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
        date_from_raw = (self.request.GET.get("date_from") or "").strip()
        date_to_raw = (self.request.GET.get("date_to") or "").strip()
        date_from = _admx_parse_optional_date(date_from_raw)
        date_to = _admx_parse_optional_date(date_to_raw)
        ops = (self.request.GET.get("ops") or "").strip()
        deleted_days = (self.request.GET.get("days") or "").strip()
        deleted_count = (self.request.GET.get("count") or "").strip()

        logs_qs = Logging.objects.select_related("user").only(
            "id",
            "datetime",
            "category",
            "log_level",
            "message",
            "user__user_id",
        ).order_by("-datetime", "-id")
        if query:
            logs_qs = logs_qs.filter(Q(message__icontains=query) | Q(user__user_id__icontains=query))
        if level:
            logs_qs = logs_qs.filter(log_level=level)
        if date_from:
            logs_qs = logs_qs.filter(datetime__date__gte=date_from)
        if date_to:
            logs_qs = logs_qs.filter(datetime__date__lte=date_to)

        context.update(
            {
                **self._base_context(),
                "logs_page": self._paginate(logs_qs, per_page=50),
                "q": query,
                "level": level,
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "level_choices": ("TRACE", "DEBUG", "INFO", "WARNING", "FATAL", "SUCCESS"),
                "page_qs": self._page_qs(),
                "reset_url": reverse("admindashboardx:logs"),
                "ops": ops,
                "deleted_days": deleted_days,
                "deleted_count": deleted_count,
            }
        )
        return context


class GlobalSearchView(DashboardBaseView):
    """GET ?q= — редирект на транзакцию / пользователя по числу или страница быстрых ссылок."""

    template_name = "admindashboardx/global_search.html"
    page_title = "AdminDashboardX · Поиск"
    page_key = "global_search"

    def get(self, request, *args, **kwargs):
        q = (request.GET.get("q") or "").strip()
        if q.isdigit():
            n = int(q)
            if Transaction.objects.filter(pk=n).exists():
                return redirect(reverse("admindashboardx:transaction_detail", kwargs={"tx_id": n}))
            if TelegramUser.objects.filter(user_id=n).exists():
                return redirect(reverse("admindashboardx:user_detail", kwargs={"telegram_user_id": n}))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        quick_links = []
        if q:
            quick_links = [
                ("Транзакции", f"{reverse('admindashboardx:transactions')}?{urlencode({'q': q})}"),
                ("Пользователи", f"{reverse('admindashboardx:users')}?{urlencode({'q': q})}"),
                ("Логи", f"{reverse('admindashboardx:logs')}?{urlencode({'q': q})}"),
            ]
        context.update({**self._base_context(), "search_q": q, "quick_links": quick_links})
        return context


class FunnelAnalyticsView(DashboardBaseView):
    """Упрощённая воронка: регистрации за окно и доля с первым успешным платежом в течение 7 дней."""

    template_name = "admindashboardx/funnel_analytics.html"
    page_title = "AdminDashboardX · Воронка регистраций"
    page_key = "funnel_analytics"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        range_days = RevenueAnalyticsView._parse_range_days(self.request.GET.get("days"))
        now = timezone.now()
        start_dt = now - timedelta(days=range_days)
        start_date = timezone.localtime(start_dt).date()
        today = timezone.localdate()
        tz = timezone.get_current_timezone()
        incoming_ok = RevenueAnalyticsView._INCOMING_OK

        total_cohort = TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today).count()
        cohort_slice = (
            TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today)
            .order_by("-join_date")
            .values("id", "join_date")[:8000]
        )

        new_users_n = 0
        paid_within_7 = 0
        for row in cohort_slice:
            new_users_n += 1
            jd = row["join_date"]
            end = jd + timedelta(days=7)
            if Transaction.objects.filter(
                incoming_ok,
                user_id=row["id"],
                timestamp__date__gte=jd,
                timestamp__date__lte=end,
            ).exclude(side="Вывод средств").exists():
                paid_within_7 += 1

        conv_7 = (paid_within_7 / new_users_n * 100) if new_users_n else 0.0

        try:
            weekly_rows = list(
                TelegramUser.objects.filter(join_date__gte=start_date, join_date__lte=today)
                .annotate(week=TruncWeek("join_date", tzinfo=tz))
                .values("week")
                .annotate(registrations=Count("id"))
                .order_by("week")
            )
        except Exception:
            weekly_rows = []

        context.update(
            {
                **self._base_context(),
                "range_days": range_days,
                "days_choices": (30, 90, 180, 365),
                "period_start": start_date,
                "period_end": today,
                "total_cohort": total_cohort,
                "new_users_n": new_users_n,
                "paid_within_7": paid_within_7,
                "conv_7_pct": round(conv_7, 2),
                "sample_capped": total_cohort > new_users_n,
                "weekly_rows": weekly_rows,
                "page_qs": self._page_qs(),
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
            "category",
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


class ProjectManagementView(DashboardBaseView):
    template_name = "admindashboardx/project_management.html"
    page_title = "AdminDashboardX · Управление проектом"
    page_key = "project_management"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return self._forbidden_response()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_tab = (self.request.GET.get("tab") or "tasks").strip()
        if active_tab not in ("tasks",):
            active_tab = "tasks"

        task_cards = []
        for task_key, meta in MANUAL_TASKS.items():
            last_run = (
                ManualTaskRun.objects.filter(task_key=task_key)
                .select_related("started_by")
                .order_by("-id")
                .first()
            )
            is_running = ManualTaskRun.objects.filter(
                task_key=task_key,
                status__in=(ManualTaskRun.STATUS_PENDING, ManualTaskRun.STATUS_RUNNING),
            ).exists()
            task_cards.append(
                {
                    "key": task_key,
                    "title": meta["title"],
                    "description": meta["description"],
                    "icon": meta.get("icon", "bi-gear"),
                    "last_run": last_run,
                    "is_running": is_running,
                    "supports_dry_run": meta.get("supports_dry_run", False),
                }
            )

        recent_runs = (
            ManualTaskRun.objects.select_related("started_by")
            .order_by("-id")[:30]
        )
        context.update(
            {
                "active_tab": active_tab,
                "task_cards": task_cards,
                "recent_runs": recent_runs,
            }
        )
        return context


class ManualTaskStartView(DashboardBaseView, View):
    page_key = "project_management"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return JsonResponse({"detail": "forbidden"}, status=403)
        if request.method != "POST":
            return JsonResponse({"detail": "method not allowed"}, status=405)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, task_key, *args, **kwargs):
        if task_key not in MANUAL_TASKS:
            return JsonResponse({"detail": "unknown task"}, status=404)

        if ManualTaskRun.objects.filter(
            task_key=task_key,
            status__in=(ManualTaskRun.STATUS_PENDING, ManualTaskRun.STATUS_RUNNING),
        ).exists():
            return JsonResponse(
                {"detail": "Задача уже выполняется. Дождитесь завершения."},
                status=409,
            )

        meta = MANUAL_TASKS[task_key]
        dry_run = self._parse_dry_run(request)
        if dry_run and not meta.get("supports_dry_run"):
            return JsonResponse({"detail": "dry-run не поддерживается для этой задачи"}, status=400)

        run = ManualTaskRun.objects.create(
            task_key=task_key,
            status=ManualTaskRun.STATUS_PENDING,
            started_by=request.user if request.user.is_authenticated else None,
            is_dry_run=dry_run,
        )
        mode_note = " (пробный dry-run)" if dry_run else ""
        ManualTaskLog.objects.create(
            run=run,
            log_level="INFO",
            message=f"Запуск задачи «{meta['title']}»{mode_note} инициирован из панели.",
        )

        from celery import current_app

        current_app.send_task(meta["celery_task_name"], args=[run.id])

        return JsonResponse(
            {
                "run_id": run.id,
                "task_key": task_key,
                "status": run.status,
                "status_label": run.get_status_display(),
                "is_dry_run": run.is_dry_run,
            }
        )

    @staticmethod
    def _parse_dry_run(request):
        if request.content_type and "application/json" in request.content_type:
            try:
                body = json.loads(request.body.decode("utf-8") or "{}")
                return bool(body.get("dry_run"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
        return request.POST.get("dry_run") in ("1", "true", "on", "yes")


class ManualTaskRunStatusView(DashboardBaseView, View):
    page_key = "project_management"

    def dispatch(self, request, *args, **kwargs):
        if self._is_support():
            return JsonResponse({"detail": "forbidden"}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, run_id, *args, **kwargs):
        run = get_object_or_404(ManualTaskRun, pk=run_id)
        after_id = request.GET.get("after_id")
        try:
            after_id = int(after_id) if after_id else 0
        except (TypeError, ValueError):
            after_id = 0

        logs_qs = run.logs.filter(id__gt=after_id).order_by("id")[:500]
        logs = [
            {
                "id": row.id,
                "level": row.log_level,
                "message": row.message,
                "created_at": timezone.localtime(row.created_at).strftime("%d.%m.%Y %H:%M:%S"),
            }
            for row in logs_qs
        ]

        return JsonResponse(
            {
                "run_id": run.id,
                "task_key": run.task_key,
                "status": run.status,
                "status_label": run.get_status_display(),
                "summary": run.summary,
                "error_message": run.error_message,
                "started_at": timezone.localtime(run.started_at).strftime("%d.%m.%Y %H:%M:%S")
                if run.started_at
                else None,
                "finished_at": timezone.localtime(run.finished_at).strftime("%d.%m.%Y %H:%M:%S")
                if run.finished_at
                else None,
                "is_dry_run": run.is_dry_run,
                "logs": logs,
            }
        )
