
"""
Общая логика CryptoCloud: инвойсы, JWT POSTBACK, применение успешной оплаты.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

import requests
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


def cryptocloud_test_usernames() -> set:
    raw = getattr(settings, "CRYPTOCLOUD_TEST_USERNAMES", "megafoll") or ""
    return {part.strip().lstrip("@").lower() for part in str(raw).split(",") if part.strip()}


def is_cryptocloud_allowed_for_user(telegram_user: Optional[TelegramUser]) -> bool:
    if not getattr(settings, "CRYPTOCLOUD_TEST_MODE", True):
        return True
    if telegram_user is None:
        return False
    username = (getattr(telegram_user, "username", None) or "").strip().lstrip("@").lower()
    return username in cryptocloud_test_usernames()


def credentials_for_channel(channel: str):
    channel = (channel or "site").lower()
    if channel == "bot":
        return (
            getattr(settings, "CRYPTOCLOUD_API_KEY_BOT", None) or "",
            getattr(settings, "CRYPTOCLOUD_SHOP_ID_BOT", None) or "",
            getattr(settings, "CRYPTOCLOUD_SECRET_KEY_BOT", None) or "",
        )
    return (
        getattr(settings, "CRYPTOCLOUD_API_KEY_SITE", None) or "",
        getattr(settings, "CRYPTOCLOUD_SHOP_ID_SITE", None) or "",
        getattr(settings, "CRYPTOCLOUD_SECRET_KEY_SITE", None) or "",
    )


def payment_system_for_channel(channel: str) -> str:
    return "CryptoCloudBot" if (channel or "").lower() == "bot" else "CryptoCloudSite"


def _b64url_decode(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + pad)


def verify_cryptocloud_jwt(token: str, secret: str) -> bool:
    """HS256 JWT из POSTBACK (SECRET KEY проекта). Токен живёт ~5 минут."""
    if not token or not secret or not isinstance(token, str):
        return False
    token = token.strip()
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception:
        return False
    if (header.get("alg") or "").upper() != "HS256":
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _b64url_decode(sig_b64)
    except Exception:
        return False
    if not hmac.compare_digest(expected, actual):
        return False
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return False
    now = int(time.time())
    if "nbf" in payload and now < int(payload["nbf"]):
        return False
    if "exp" in payload and now >= int(payload["exp"]):
        return False
    return True


def parse_postback_payload(request) -> dict:
    content_type = (getattr(request, "content_type", None) or "").lower()
    if "json" in content_type:
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    if hasattr(request, "POST") and request.POST:
        return {k: request.POST.get(k) for k in request.POST}
    try:
        data = json.loads(request.body or b"{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def create_invoice(*, channel: str, amount, order_id, email: Optional[str] = None) -> dict:
    api_key, shop_id, _secret = credentials_for_channel(channel)
    if not api_key or not shop_id:
        raise RuntimeError(f"CryptoCloud: нет API key / shop_id для канала {channel}")
    base = getattr(settings, "CRYPTOCLOUD_API_BASE", "https://api.cryptocloud.plus/v2").rstrip("/")
    url = f"{base}/invoice/create"
    currency = getattr(settings, "CRYPTOCLOUD_CURRENCY", "RUB") or "RUB"
    payload = {
        "shop_id": shop_id,
        "amount": float(amount),
        "currency": currency,
        "order_id": str(order_id),
    }
    if email:
        payload["email"] = email
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success" or not body.get("result"):
        raise RuntimeError(f"CryptoCloud error: {body}")
    return body["result"]


def json_ok() -> JsonResponse:
    return JsonResponse({"message": "Postback received"}, status=200)


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


def find_transaction_from_postback(data: dict) -> Optional[Transaction]:
    order_id = data.get("order_id")
    if order_id not in (None, ""):
        try:
            tx = Transaction.objects.filter(pk=int(order_id)).first()
            if tx:
                return tx
        except (TypeError, ValueError):
            tx = Transaction.objects.filter(payment_id=str(order_id)).first()
            if tx:
                return tx
    invoice_info = data.get("invoice_info") or {}
    uuid = invoice_info.get("uuid") or data.get("invoice_id")
    if uuid:
        return Transaction.objects.filter(payment_id=str(uuid)).first()
    return None


def apply_successful_pay(
    *,
    transaction: Transaction,
    telegram_user: TelegramUser,
    payment_id: str,
    channel: str,
    log_prefix: str,
) -> bool:
    """Идемпотентно применяет успешный POSTBACK. Дни — по рублёвой сумме Transaction."""
    amount_value = Decimal(transaction.amount)
    if transaction.status == "succeeded" and transaction.paid:
        if channel and channel != (telegram_user.cryptocloud_channel or ""):
            telegram_user.cryptocloud_channel = channel
            telegram_user.save(update_fields=["cryptocloud_channel"])
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
        telegram_user.cryptocloud_channel = channel or telegram_user.cryptocloud_channel or "site"
        telegram_user.permission_revoked = False
        telegram_user.save()

        tx.status = "succeeded"
        tx.paid = True
        if payment_id:
            tx.payment_id = str(payment_id)
        tx.payment_system = tx.payment_system or payment_system_for_channel(channel)
        tx.save()

        _apply_referrals(telegram_user, tx, amount_value)

    Logging.objects.create(
        category="payment",
        log_level="SUCCESS",
        message=(
            f"{log_prefix} [Платёж {amount_value} прошёл] "
            f"[days={days}] [invoice={payment_id}] [tx={transaction.id}]"
        ),
        datetime=datetime.now(),
        user=telegram_user,
    )
    return True
