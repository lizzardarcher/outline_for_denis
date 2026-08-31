
"""
Общая логика CloudPayments: HMAC webhooks, AccountId, применение успешного Pay.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction as db_transaction
from django.http import JsonResponse

from apps.payment.robokassa_subscription import (
    extend_telegram_user_subscription,
    resolve_subscription_days,
)
from bot.models import (
    Logging,
    ReferralSettings,
    ReferralTransaction,
    TelegramReferral,
    TelegramUser,
    Transaction,
)

# ReasonCode: https://developers.cloudpayments.ru/ — справочник ошибок
REASON_CLEAR_TOKEN = frozenset({
    5054,  # ExpiredCard
    5055,  # LostCard / Stolen-like
    5057,  # StolenCard
    5059,  # RestrictedCard
    5061,  # PickUpCard
    5062,  # Card is blocked
    5063,  # Card is restricted
    5065,  # Card is lost
    5082,  # Invalid card number / issuer decline variants
})
REASON_KEEP_TOKEN = frozenset({
    5051,  # InsufficientFunds
    5006,  # Decline by issuer temporary
})



def default_account_id(telegram_user: TelegramUser) -> str:
    existing = (telegram_user.cloudpayments_account_id or "").strip()
    if existing:
        return existing
    return f"tg:{telegram_user.user_id}"


def credentials_for_channel(channel: str):
    channel = (channel or "site").lower()
    if channel == "bot":
        return (
            getattr(settings, "CLOUDPAYMENTS_PUBLIC_ID_BOT", None) or "",
            getattr(settings, "CLOUDPAYMENTS_API_SECRET_BOT", None) or "",
        )
    return (
        getattr(settings, "CLOUDPAYMENTS_PUBLIC_ID_SITE", None) or "",
        getattr(settings, "CLOUDPAYMENTS_API_SECRET_SITE", None) or "",
    )


def payment_system_for_channel(channel: str) -> str:
    return "CloudPaymentsBot" if (channel or "").lower() == "bot" else "CloudPaymentsSite"


def verify_cloudpayments_hmac(raw_body: bytes, api_secret: str, request) -> bool:
    """Проверка Content-HMAC / X-Content-HMAC (HMAC-SHA256, base64, ключ = API Secret)."""
    if not api_secret:
        return False
    headers = request.headers
    candidates = [
        headers.get("Content-HMAC") or headers.get("Content-Hmac"),
        headers.get("X-Content-HMAC") or headers.get("X-Content-Hmac"),
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return False

    digest = base64.b64encode(
        hmac.new(api_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("ascii")
    return any(hmac.compare_digest(digest, c.strip()) for c in candidates)


def json_code(code: int, status: int = 200) -> JsonResponse:
    return JsonResponse({"code": code}, status=status)


def _apply_referrals(telegram_user: TelegramUser, transaction: Transaction, amount_value: Decimal) -> None:
    referral_percentages = {
        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
    }
    referred_list = TelegramReferral.objects.filter(referred=telegram_user).select_related("referrer")
    if not referred_list:
        return
    user_ids_to_pay = [r.referrer.user_id for r in referred_list]
    users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}
    for r in referred_list:
        user_to_pay = users_to_pay.get(r.referrer.user_id)
        if not user_to_pay:
            continue
        percent = referral_percentages.get(r.level)
        if user_to_pay.special_offer:
            percent = {
                1: user_to_pay.special_offer.level_1_percentage,
                2: user_to_pay.special_offer.level_2_percentage,
                3: user_to_pay.special_offer.level_3_percentage,
                4: user_to_pay.special_offer.level_4_percentage,
                5: user_to_pay.special_offer.level_5_percentage,
            }.get(r.level)
        if not percent:
            continue
        income_delta = Decimal(amount_value) * Decimal(percent) / Decimal(100)
        user_to_pay.income = Decimal(user_to_pay.income) + income_delta
        user_to_pay.save(update_fields=["income"])
        ReferralTransaction.objects.create(
            referral=r,
            amount=income_delta,
            transaction=transaction,
        )


def apply_successful_pay(
    *,
    transaction: Transaction,
    telegram_user: TelegramUser,
    amount_value: Decimal,
    payment_id: str,
    token: str,
    channel: str,
    log_prefix: str,
) -> bool:
    """
    Идемпотентно применяет успешный Pay / tokens/charge.
    Возвращает True, если подписка была применена (или уже была применена ранее).
    """
    if transaction.status == "succeeded" and transaction.paid:
        # Обновим токен, если пришёл новый
        if token and token != (telegram_user.cloudpayments_token or ""):
            telegram_user.cloudpayments_token = token
            telegram_user.cloudpayments_account_id = default_account_id(telegram_user)
            telegram_user.cloudpayments_channel = channel
            telegram_user.save(
                update_fields=["cloudpayments_token", "cloudpayments_account_id", "cloudpayments_channel"]
            )
        return True

    days = resolve_subscription_days(amount_value)
    if days <= 0:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=f"{log_prefix} [Неизвестная сумма {amount_value}, дни=0]",
            datetime=datetime.now(),
            user=telegram_user,
        )

    with db_transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=transaction.pk)
        if tx.status == "succeeded" and tx.paid:
            return True

        extend_telegram_user_subscription(telegram_user, days)
        if token:
            telegram_user.cloudpayments_token = token
        telegram_user.cloudpayments_account_id = default_account_id(telegram_user)
        telegram_user.cloudpayments_channel = channel or telegram_user.cloudpayments_channel or "site"
        telegram_user.permission_revoked = False
        telegram_user.save()

        tx.status = "succeeded"
        tx.paid = True
        tx.amount = amount_value
        tx.currency = tx.currency or "RUB"
        tx.payment_id = str(payment_id)
        tx.payment_system = tx.payment_system or payment_system_for_channel(channel)
        tx.save()

        _apply_referrals(telegram_user, tx, amount_value)

    Logging.objects.create(
        category="payment",
        log_level="SUCCESS",
        message=(
            f"{log_prefix} [Платёж {amount_value} р. прошёл] "
            f"[days={days}] [TransactionId={payment_id}] [tx={transaction.id}]"
        ),
        datetime=datetime.now(),
        user=telegram_user,
    )
    return True


def apply_fail_side_effects(
    *,
    telegram_user: TelegramUser,
    reason_code: Optional[int],
    transaction: Optional[Transaction],
    log_prefix: str,
) -> None:
    if transaction and transaction.status != "succeeded":
        transaction.status = "canceled"
        transaction.paid = False
        transaction.save(update_fields=["status", "paid"])

    code = int(reason_code) if reason_code is not None else None
    msg = f"{log_prefix} [Fail] user={telegram_user.user_id} ReasonCode={code}"
    if code in REASON_CLEAR_TOKEN:
        telegram_user.cloudpayments_token = ""
        telegram_user.save(update_fields=["cloudpayments_token"])
        msg += " [токен сброшен]"
    elif code in REASON_KEEP_TOKEN:
        msg += " [токен сохранён]"
    Logging.objects.create(
        category="payment",
        log_level="WARNING",
        message=msg,
        datetime=datetime.now(),
        user=telegram_user,
    )


def find_transaction_by_invoice(invoice_id: str) -> Optional[Transaction]:
    if not invoice_id:
        return None
    try:
        return Transaction.objects.filter(pk=int(invoice_id)).first()
    except (TypeError, ValueError):
        return Transaction.objects.filter(payment_id=str(invoice_id)).first()
