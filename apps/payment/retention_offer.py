"""
Спецпредложение «1 месяц special» при отмене подписки.
Цена берётся из Prices.price_special (админка).
Кулдаун — RETENTION_OFFER_COOLDOWN_MONTHS (.env, по умолчанию 3 месяца).
"""
from __future__ import annotations

import calendar
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple, Union

from django.conf import settings
from django.utils import timezone

from bot.models import Prices, TelegramUser

AmountLike = Union[int, float, Decimal, str, None]

BOT_PLAN_LABELS = {
    "1": "1 Месяц",
    "2": "3 Месяца",
    "3": "6 Месяцев",
    "4": "1 Год",
    "3_days_trial": "3 Дня",
    "special": "1 Месяц со скидкой",
}


def _as_int_amount(value: AmountLike) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def get_prices() -> Prices:
    return Prices.objects.get(pk=1)


def special_month_price(prices: Optional[Prices] = None) -> Optional[int]:
    prices = prices or get_prices()
    value = prices.price_special
    if value is None:
        return None
    amount = int(value)
    if amount <= 0:
        return None
    return amount


def cooldown_months() -> int:
    try:
        months = int(getattr(settings, "RETENTION_OFFER_COOLDOWN_MONTHS", 3) or 3)
    except (TypeError, ValueError):
        months = 3
    if months < 0:
        return 3
    return months


def add_calendar_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def is_special_amount(amount: AmountLike, prices: Optional[Prices] = None) -> bool:
    special = special_month_price(prices)
    amount_int = _as_int_amount(amount)
    if special is None or amount_int is None:
        return False
    return amount_int == special


def is_retention_offer_available(user: Optional[TelegramUser], prices: Optional[Prices] = None) -> bool:
    if user is None:
        return False
    if special_month_price(prices) is None:
        return False
    last = user.last_special_month_offer_at
    if last is None:
        return True
    if timezone.is_naive(last):
        last = timezone.make_aware(last, timezone.get_current_timezone())
    return timezone.now() >= add_calendar_months(last, cooldown_months())


def mark_retention_offer_used_if_amount(user: Optional[TelegramUser], amount: AmountLike) -> None:
    if user is None or not is_special_amount(amount):
        return
    user.last_special_month_offer_at = timezone.now()
    user.save(update_fields=["last_special_month_offer_at"])


def days_for_amount(amount: AmountLike, prices: Optional[Prices] = None) -> int:
    prices = prices or get_prices()
    amount_int = _as_int_amount(amount)
    if amount_int is None:
        return 0
    if prices.price_1 is not None and amount_int == int(prices.price_1):
        return 31
    if prices.price_2 is not None and amount_int == int(prices.price_2):
        return 93
    if prices.price_3 is not None and amount_int == int(prices.price_3):
        return 184
    if prices.price_4 is not None and amount_int == int(prices.price_4):
        return 366
    special = special_month_price(prices)
    if special is not None and amount_int == special:
        return 31
    if prices.price_5 is not None and amount_int == int(prices.price_5):
        return 3
    return 0


def amount_days_from_posted(subscription: AmountLike, prices: Optional[Prices] = None) -> Tuple[float, int]:
    prices = prices or get_prices()
    posted = _as_int_amount(subscription)
    if posted is None:
        return 0.0, 0
    days = days_for_amount(posted, prices)
    if days <= 0:
        return 0.0, 0
    return float(posted), days


def resolve_purchase_for_user(
    subscription: AmountLike,
    user: Optional[TelegramUser],
    prices: Optional[Prices] = None,
) -> Tuple[float, int]:
    prices = prices or get_prices()
    amount, days = amount_days_from_posted(subscription, prices)
    if amount <= 0 or days <= 0:
        return 0.0, 0
    if is_special_amount(amount, prices) and not is_retention_offer_available(user, prices):
        return 0.0, 0
    return amount, days


def bot_plan_amount_days(plan_key: str, prices: Optional[Prices] = None) -> Tuple[Optional[int], Optional[int]]:
    prices = prices or get_prices()
    mapping = {
        "1": (prices.price_1, 31),
        "2": (prices.price_2, 93),
        "3": (prices.price_3, 186),
        "4": (prices.price_4, 366),
        "3_days_trial": (prices.price_5, 3),
        "special": (special_month_price(prices), 31),
    }
    amount, days = mapping.get(plan_key, (None, None))
    if amount is None or int(amount) <= 0 or not days:
        return None, None
    return int(amount), int(days)


def resolve_bot_plan_for_user(
    plan_key: str,
    user: Optional[TelegramUser],
    prices: Optional[Prices] = None,
) -> Tuple[Optional[int], Optional[int]]:
    prices = prices or get_prices()
    amount, days = bot_plan_amount_days(plan_key, prices)
    if amount is None or days is None:
        return None, None
    if plan_key == "special" and not is_retention_offer_available(user, prices):
        return None, None
    return amount, days
