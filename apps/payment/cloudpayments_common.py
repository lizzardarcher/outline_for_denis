
"""
Общая логика CloudPayments: HMAC webhooks, AccountId, применение успешного Pay,
опрос зависших pending-транзакций.
"""


from __future__ import annotations

import base64
import hashlib
import hmac
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional


import requests
from django.conf import settings
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.utils import timezone

from apps.payment.robokassa_subscription import (
    extend_telegram_user_subscription,
    is_pending_old_enough_to_abandon,
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

CLOUDPAYMENTS_PENDING_LOOKBACK_DAYS = 7
CLOUDPAYMENTS_ABANDON_AFTER = timedelta(hours=24)
CLOUDPAYMENTS_PENDING_API_TIMEOUT = 15
_PAID_STATUSES = frozenset({"Completed"})
_CANCELED_STATUSES = frozenset({"Declined", "Cancelled", "Canceled"})
_PENDING_STATUSES = frozenset({"AwaitingAuthentication", "Authorized"})



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


        extend_telegram_user_subscription(telegram_user, days, amount=amount_value)
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


def classify_cloudpayments_status(status: str) -> str:
    """paid | canceled | pending | unknown"""
    value = (status or "").strip()
    if value in _PAID_STATUSES:
        return "paid"
    if value in _CANCELED_STATUSES:
        return "canceled"
    if value in _PENDING_STATUSES:
        return "pending"
    return "unknown"


def has_pending_cloudpayments_charge(user: TelegramUser, payment_system: str) -> bool:
    """Свежий pending (виджет или рекуррент) блокирует новое списание."""
    lookback = timezone.now() - timedelta(days=CLOUDPAYMENTS_PENDING_LOOKBACK_DAYS)
    return Transaction.objects.filter(
        user=user,
        payment_system=payment_system,
        status="pending",
        paid=False,
        timestamp__gte=lookback,
    ).exists()


def _model_from_cp_response(data: Optional[dict]) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    model = data.get("Model")
    if isinstance(model, dict) and (model.get("Status") or model.get("TransactionId")):
        return model
    return None


def _cp_api_post(
    path: str,
    payload: dict,
    public_id: str,
    api_secret: str,
    *,
    timeout: int = CLOUDPAYMENTS_PENDING_API_TIMEOUT,
) -> Optional[dict]:
    base = getattr(settings, "CLOUDPAYMENTS_API_BASE", "https://api.cloudpayments.ru").rstrip("/")
    url = f"{base}{path}"
    try:
        response = requests.post(
            url,
            json=payload,
            auth=(public_id, api_secret),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        return response.json()
    except Exception:
        return None


def _is_cp_not_found(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        return False
    if _model_from_cp_response(data):
        return False
    message = str(data.get("Message") or "").strip().lower()
    return (not data.get("Success")) and ("not found" in message)


def _mark_abandoned_pending(transaction: Transaction, log_prefix: str) -> None:
    """Брошенный инвойс: canceled без сброса токена карты."""
    if transaction.status == "succeeded":
        return
    transaction.status = "canceled"
    transaction.paid = False
    transaction.save(update_fields=["status", "paid"])
    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f"{log_prefix} Нет платежа в CloudPayments, отменён как брошенный tx={transaction.id}",
        datetime=timezone.now(),
        user=transaction.user if getattr(transaction, "user", None) else None,
    )


def fetch_cloudpayments_payment(
    transaction: Transaction,
    public_id: str,
    api_secret: str,
    *,
    timeout: int = CLOUDPAYMENTS_PENDING_API_TIMEOUT,
) -> tuple[Optional[dict], str]:
    """
    Ищет платёж в CP: сначала /payments/find по InvoiceId=tx.id,
    затем /payments/get по TransactionId, если payment_id уже известен.
    Возвращает (model, kind): found | not_found | error.
    """
    data = _cp_api_post(
        "/payments/find",
        {"InvoiceId": str(transaction.id)},
        public_id,
        api_secret,
        timeout=timeout,
    )
    if data is None:
        return None, "error"
    model = _model_from_cp_response(data)
    if model:
        return model, "found"

    payment_id = str(transaction.payment_id or "").strip()
    if payment_id.isdigit():
        data_get = _cp_api_post(
            "/payments/get",
            {"TransactionId": int(payment_id)},
            public_id,
            api_secret,
            timeout=timeout,
        )
        if data_get is None:
            return None, "error"
        model = _model_from_cp_response(data_get)
        if model:
            return model, "found"
        if _is_cp_not_found(data_get) or _is_cp_not_found(data):
            return None, "not_found"
        return None, "error"

    if _is_cp_not_found(data):
        return None, "not_found"
    return None, "error"


def reconcile_cloudpayments_pending_transaction(
    transaction: Transaction,
    *,
    public_id: str,
    api_secret: str,
    channel: str,
    source_label: str,
) -> str:
    """
    Сверяет pending-транзакцию с CloudPayments.
    Возвращает: paid | canceled | pending | error | unknown
    """
    log_prefix = f"[{source_label}] [pending-check]"
    model, fetch_kind = fetch_cloudpayments_payment(transaction, public_id, api_secret)
    if fetch_kind == "not_found":
        if is_pending_old_enough_to_abandon(transaction, CLOUDPAYMENTS_ABANDON_AFTER):
            _mark_abandoned_pending(transaction, log_prefix)
            return "canceled"
        return "pending"
    if fetch_kind != "found" or not model:
        return "error"

    kind = classify_cloudpayments_status(model.get("Status") or "")
    telegram_user = transaction.user
    cp_tx_id = model.get("TransactionId")

    if kind == "paid":
        if not telegram_user:
            return "error"
        amount_raw = model.get("Amount") or model.get("PaymentAmount") or transaction.amount
        try:
            amount_value = Decimal(str(amount_raw))
        except Exception:
            amount_value = Decimal(transaction.amount)
        apply_successful_pay(
            transaction=transaction,
            telegram_user=telegram_user,
            amount_value=amount_value,
            payment_id=str(cp_tx_id or transaction.payment_id or transaction.id),
            token=str(model.get("Token") or ""),
            channel=channel,
            log_prefix=log_prefix,
        )
        return kind

    if kind == "canceled":
        if cp_tx_id and not transaction.payment_id:
            transaction.payment_id = str(cp_tx_id)
            transaction.save(update_fields=["payment_id"])
        reason_code = model.get("ReasonCode")
        if telegram_user:
            apply_fail_side_effects(
                telegram_user=telegram_user,
                reason_code=reason_code,
                transaction=transaction,
                log_prefix=log_prefix,
            )
        elif transaction.status != "succeeded":
            transaction.status = "canceled"
            transaction.paid = False
            transaction.save(update_fields=["status", "paid"])
        return kind

    if kind == "unknown":
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=(
                f"{log_prefix} Неизвестный Status={model.get('Status')} "
                f"tx={transaction.id} cp={cp_tx_id}"
            ),
            datetime=timezone.now(),
            user=telegram_user,
        )
    return kind


def check_cloudpayments_pending_transactions(*, channel: str, source_label: str) -> None:
    public_id, api_secret = credentials_for_channel(channel)
    if not public_id or not api_secret:
        Logging.objects.create(
            category="payment",
            log_level="DANGER",
            message=f"[{source_label}] [pending-check] Не заданы CloudPayments Public ID / API Secret",
            datetime=timezone.now(),
        )
        return

    payment_system = payment_system_for_channel(channel)
    lookback = timezone.now() - timedelta(days=CLOUDPAYMENTS_PENDING_LOOKBACK_DAYS)
    pending_qs = Transaction.objects.filter(
        status="pending",
        paid=False,
        payment_system=payment_system,
        timestamp__gte=lookback,
    ).select_related("user")

    for transaction in pending_qs:
        try:
            reconcile_cloudpayments_pending_transaction(
                transaction,
                public_id=public_id,
                api_secret=api_secret,
                channel=channel,
                source_label=source_label,
            )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=(
                    f"[{source_label}] [pending-check] Ошибка tx={transaction.id} "
                    f"payment_id={transaction.payment_id}\n{traceback.format_exc()}"
                ),
                datetime=timezone.now(),
                user=transaction.user if getattr(transaction, "user", None) else None,
            )
