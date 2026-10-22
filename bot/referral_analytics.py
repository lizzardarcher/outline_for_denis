"""Когорта прямых рефералов: регистрации и оплаты за период."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook

from bot.models import ReferralTransaction, TelegramReferral, TelegramUser, Transaction

SUCCESS_Q = Q(paid=True) | Q(status="succeeded")
WITHDRAWAL_SIDE = "Вывод средств"
_BIGINT_MAX = 9223372036854775807


def search_referrers(query, limit=25):
    query = (query or "").strip()
    if not query:
        return []
    filters = (
        Q(username__icontains=query)
        | Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
    )
    if query.isdigit():
        value = int(query)
        if value <= _BIGINT_MAX:
            filters |= Q(user_id=value)
    return list(
        TelegramUser.objects.filter(filters)
        .annotate(
            direct_referrals=Count(
                "given_referrals",
                filter=Q(given_referrals__level=1),
            )
        )
        .order_by("-direct_referrals", "username", "user_id")[:limit]
    )


def parse_period(params, today=None):
    today = today or timezone.localdate()
    preset = (params.get("preset") or "").strip()
    if preset == "7":
        return today - timedelta(days=6), today, None
    if preset == "30":
        return today - timedelta(days=29), today, None
    if preset == "month":
        return today.replace(day=1), today, None

    raw_from = (params.get("date_from") or "").strip()
    raw_to = (params.get("date_to") or "").strip()
    if not raw_from and not raw_to:
        return today - timedelta(days=29), today, None
    try:
        date_from = datetime.strptime(raw_from, "%Y-%m-%d").date() if raw_from else today - timedelta(days=29)
        date_to = datetime.strptime(raw_to, "%Y-%m-%d").date() if raw_to else today
    except ValueError:
        return None, None, "Укажите даты в формате ГГГГ-ММ-ДД."
    if date_from > date_to:
        return None, None, "Дата начала позже даты конца."
    return date_from, date_to, None


def _as_local(ts):
    if ts is None:
        return None
    if timezone.is_aware(ts):
        return timezone.localtime(ts)
    # Naive: считаем уже в текущей TIME_ZONE (как пишет datetime.now() на сервере).
    return timezone.make_aware(ts, timezone.get_current_timezone())


def _period_datetimes(date_from, date_to):
    """[start, end) в текущей TIME_ZONE — границы календарных дней периода."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), tz)
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz)
    return start, end


def _in_period(ts, date_from, date_to):
    local = _as_local(ts)
    if local is None:
        return False
    day = local.date()
    return date_from <= day <= date_to



def _payment_row(tx, referred_by_id):
    local_ts = _as_local(tx.timestamp)
    return {
        "user": tx.user or referred_by_id.get(tx.user_id),
        "paid_at": local_ts,
        "amount": tx.amount or Decimal("0"),
        "tx_id": tx.pk,
        "user_id": tx.user_id,
    }


def build_report(referrer, date_from, date_to):
    """
    Новые за период — join_date в периоде.
    Оплаты/начисления — timestamp в периоде по всем прямым рефералам;
    отдельно список оплат только от новых.
    """
    all_direct = list(
        TelegramReferral.objects.filter(referrer=referrer, level=1)
        .select_related("referred")
        .order_by("referred__join_date", "referred_id")
    )
    cohort_users = [
        row.referred for row in all_direct
        if row.referred.join_date and date_from <= row.referred.join_date <= date_to
    ]
    cohort_ids = {user.pk for user in cohort_users}
    all_referred_ids = [row.referred_id for row in all_direct]
    referred_by_id = {row.referred_id: row.referred for row in all_direct}

    start_dt, end_dt = _period_datetimes(date_from, date_to)
    payments = []
    if all_referred_ids:
        qs = (
            Transaction.objects.filter(
                SUCCESS_Q,
                user_id__in=all_referred_ids,
                timestamp__date__gte=date_from,
                timestamp__date__lte=date_to,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
            )
            .exclude(side=WITHDRAWAL_SIDE)
            .select_related("user")
            .order_by("timestamp", "id")
        )
        for tx in qs:
            if _in_period(tx.timestamp, date_from, date_to):
                payments.append(tx)

    payments_by_day = {}
    payment_count = 0
    payment_sum = Decimal("0")
    payment_count_new = 0
    payment_sum_new = Decimal("0")
    payer_ids_in_period = set()
    rows_all = []
    rows_new = []
    for tx in payments:
        local_ts = _as_local(tx.timestamp)
        day = local_ts.date()
        if not (date_from <= day <= date_to):
            continue
        row = _payment_row(tx, referred_by_id)
        amount = row["amount"]
        payment_count += 1
        payment_sum += amount
        bucket = payments_by_day.setdefault(day, {"count": 0, "sum": Decimal("0")})
        bucket["count"] += 1
        bucket["sum"] += amount
        payer_ids_in_period.add(tx.user_id)
        rows_all.append(row)
        if tx.user_id in cohort_ids:
            payment_count_new += 1
            payment_sum_new += amount
            rows_new.append(row)

    referral_income_count = 0
    referral_income_sum = Decimal("0")

    referral_income_count_new = 0
    referral_income_sum_new = Decimal("0")
    if all_referred_ids:
        for rt in (
            ReferralTransaction.objects.filter(
                referral__referrer=referrer,
                referral__level=1,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
            )
            .select_related("transaction", "referral")
            .order_by("timestamp", "id")
        ):
            if not _in_period(rt.timestamp, date_from, date_to):
                continue
            amount = rt.amount or Decimal("0")
            referral_income_count += 1
            referral_income_sum += amount
            referred_id = rt.referral.referred_id if rt.referral_id else None
            if referred_id in cohort_ids:
                referral_income_count_new += 1
                referral_income_sum_new += amount

    regs_by_day = {}
    for user in cohort_users:
        regs_by_day[user.join_date] = regs_by_day.get(user.join_date, 0) + 1

    paid_by_join = {}
    for user in cohort_users:
        if user.pk in payer_ids_in_period:
            paid_by_join[user.join_date] = paid_by_join.get(user.join_date, 0) + 1

    registrations = len(cohort_users)
    paid_users = sum(1 for user in cohort_users if user.pk in payer_ids_in_period)
    if registrations:
        conversion = (Decimal(paid_users) * Decimal("100") / Decimal(registrations)).quantize(Decimal("0.1"))
    else:
        conversion = Decimal("0.0")

    daily = []
    cursor = date_from
    while cursor <= date_to:
        pay = payments_by_day.get(cursor, {"count": 0, "sum": Decimal("0")})
        daily.append({
            "date": cursor,
            "registrations": regs_by_day.get(cursor, 0),
            "paid_users": paid_by_join.get(cursor, 0),
            "payment_count": pay["count"],
            "payment_sum": pay["sum"],
        })
        cursor += timedelta(days=1)

    return {
        "referrer": referrer,
        "date_from": date_from,
        "date_to": date_to,
        "registrations": registrations,
        "paid_users": paid_users,
        "conversion_pct": conversion,
        "payment_count": payment_count,
        "payment_sum": payment_sum,
        "payment_count_new": payment_count_new,
        "payment_sum_new": payment_sum_new,
        "referral_income_count": referral_income_count,
        "referral_income_sum": referral_income_sum,
        "referral_income_count_new": referral_income_count_new,
        "referral_income_sum_new": referral_income_sum_new,
        "rows": rows_all,
        "rows_all": rows_all,
        "rows_new": rows_new,
        "daily": daily,
        "chart_labels": [day["date"].strftime("%d.%m") for day in daily],
        "chart_registrations": [day["registrations"] for day in daily],
        "chart_paid": [day["paid_users"] for day in daily],
    }


def excel_response(report):
    referrer = report["referrer"]
    wb = Workbook()
    summary = wb.active
    summary.title = "Сводка"
    summary.append(["Реферер", referrer.first_name or "", referrer.last_name or "", referrer.username or "", referrer.user_id])
    summary.append(["Период", report["date_from"].isoformat(), report["date_to"].isoformat()])
    summary.append(["Новых за период", report["registrations"]])
    summary.append(["Из них оплатили", report["paid_users"]])
    summary.append(["Конверсия новых, %", float(report["conversion_pct"])])
    summary.append(["Оплат всех рефералов за период", report["payment_count"]])
    summary.append(["Сумма оплат всех рефералов", float(report["payment_sum"])])
    summary.append(["Оплат новых за период", report["payment_count_new"]])
    summary.append(["Сумма оплат новых", float(report["payment_sum_new"])])
    summary.append(["Начислений от новых за период", report["referral_income_count_new"]])
    summary.append(["Сумма начислений от новых", float(report["referral_income_sum_new"])])
    summary.append(["Начислений всех за период", report["referral_income_count"]])
    summary.append(["Сумма начислений всех", float(report["referral_income_sum"])])

    daily_ws = wb.create_sheet("По дням")
    daily_ws.append(["Дата", "Регистрации", "Из них оплатили", "Оплат за день", "Сумма за день"])
    for day in report["daily"]:
        daily_ws.append([
            day["date"].isoformat(),
            day["registrations"],
            day["paid_users"],
            day["payment_count"],
            float(day["payment_sum"]),
        ])

    def _write_payments_sheet(title, rows):
        ws = wb.create_sheet(title)
        ws.append(["user_id", "Имя", "Фамилия", "username", "Дата оплаты", "Сумма"])
        for row in rows:
            user = row["user"]
            paid_at = row["paid_at"]
            ws.append([
                user.user_id if user else "",
                (user.first_name or "") if user else "",
                (user.last_name or "") if user else "",
                (user.username or "") if user else "",
                paid_at.strftime("%Y-%m-%d %H:%M") if paid_at else "",
                float(row["amount"]) if row["amount"] is not None else "",
            ])

    _write_payments_sheet("Платежи новые", report["rows_new"])
    _write_payments_sheet("Платежи общие", report["rows_all"])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"referral_{referrer.user_id}_{report['date_from'].isoformat()}_{report['date_to'].isoformat()}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response
