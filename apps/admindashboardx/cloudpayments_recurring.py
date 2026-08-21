
"""
Рекуррентные списания CloudPayments (tokens/charge), по образцу ukassa_recurring.
Источник истины по продлению — ответ API + идемпотентный Pay-webhook.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

from apps.payment.cloudpayments_common import (
    REASON_CLEAR_TOKEN,
    apply_successful_pay,
    credentials_for_channel,
    default_account_id,
    payment_system_for_channel,
)
from bot.models import IncomeInfo, Prices, TelegramUser, Transaction

from .task_run_logging import TaskRunLogger

DEFAULT_CP_API_TIMEOUT = 30


def _user_email(user):
    try:
        return user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
    except Exception:
        return "noemail@noemail.ru"


def _skip_reason(user: TelegramUser, expected_channel: str) -> Optional[str]:
    if user.permission_revoked:
        return "permission_revoked"
    if not (user.cloudpayments_token or "").strip():
        return "нет cloudpayments_token"
    if (getattr(user, "robokassa_recurring_parent_inv_id", "") or "").strip():
        return "активна рекуррентная подписка RoboKassa"
    if (user.payment_method_id or "").strip():
        return "активен payment_method_id ЮKassa"
    channel = (user.cloudpayments_channel or "").strip().lower()
    if channel and channel != expected_channel:
        return f"канал «{channel}» (нужен {expected_channel})"
    if not channel:
        # Без канала — бот/сайт по expected; пустой канал обрабатываем в обеих задачах только один раз:
        # site задача берёт пустой как site, bot — только явный bot.
        if expected_channel == "bot":
            return "канал не bot (пустой → site)"
    return None


def _charge_payload(user, amount, currency, invoice_id: int) -> dict:
    account_id = default_account_id(user)
    return {
        "Amount": float(amount),
        "Currency": currency,
        "AccountId": account_id,
        "Token": user.cloudpayments_token,
        "InvoiceId": str(invoice_id),
        "Description": f"Рекуррентный платеж DomVPN user={user.user_id}",
        "Email": _user_email(user),
        "TrInitiatorCode": 0,
        "PaymentScheduled": 1,
        "JsonData": {
            "cloudpayments": {
                "customerReceipt": {
                    "Items": [
                        {
                            "label": "Рекуррентный платеж DomVPN",
                            "price": float(amount),
                            "quantity": 1.0,
                            "amount": float(amount),
                            "vat": None,
                            "method": 0,
                            "object": 4,
                        }
                    ],
                    "email": _user_email(user),
                    "amounts": {
                        "electronic": float(amount),
                        "advancePayment": 0.0,
                        "credit": 0.0,
                        "provision": 0.0,
                    },
                }
            }
        },
    }


def _tokens_charge(payload, public_id, api_secret, *, timeout):
    base = getattr(settings, "CLOUDPAYMENTS_API_BASE", "https://api.cloudpayments.ru").rstrip("/")
    url = f"{base}/payments/tokens/charge"
    started = time.monotonic()
    try:
        response = requests.post(
            url,
            json=payload,
            auth=(public_id, api_secret),
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": str(uuid.uuid4()),
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        elapsed = time.monotonic() - started
        raise TimeoutError(f"CloudPayments API: таймаут {timeout}s ({elapsed:.1f}s)") from exc
    except requests.RequestException as exc:
        elapsed = time.monotonic() - started
        raise RuntimeError(f"CloudPayments API: сеть за {elapsed:.1f}s: {exc}") from exc

    elapsed = time.monotonic() - started
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"CloudPayments API: HTTP {response.status_code}, не JSON: {(response.text or '')[:200]}"
        ) from exc
    return data, elapsed


def _run_channel(channel: str, logger: TaskRunLogger, *, dry_run=False, api_timeout=DEFAULT_CP_API_TIMEOUT):
    expected = channel.lower()  # bot | site
    label = channel.upper()
    users = list(
        TelegramUser.objects.filter(
            subscription_status=False,
            permission_revoked=False,
            cloudpayments_token__isnull=False,
        ).exclude(cloudpayments_token="")
    )

    mode = "DRY-RUN" if dry_run else "Списание"
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{label}] [CloudPayments] [{mode}] "
        f"[кандидатов: {len(users)}]",
    )

    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
    currency = "RUB"
    success = failed = skipped = canceled = 0

    eligible = []
    for user in users:
        reason = _skip_reason(user, expected)
        if reason:
            skipped += 1
            if dry_run:
                logger.log(
                    "DEBUG",
                    f"[DRY-RUN] [{label}] Пропуск user_id={user.user_id}: {reason}",
                    user=user,
                )
            continue
        eligible.append(user)

    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{label}] К списанию: {len(eligible)} "
        f"(пропущено: {skipped})",
    )

    public_id, api_secret = credentials_for_channel(expected)
    payment_system = payment_system_for_channel(expected)

    for idx, user in enumerate(eligible, 1):
        prefix = f"[#{idx:03d}/{len(eligible):03d}] "
        if dry_run:
            logger.log(
                "INFO",
                f"{prefix}[DRY-RUN] [{label}] charge user={user.user_id} "
                f"amount={amount_to_charge} token={(user.cloudpayments_token or '')[:12]}…",
                user=user,
            )
            continue

        if not public_id or not api_secret:
            failed += 1
            logger.log(
                "FATAL",
                f"{prefix}[{label}] Нет Public ID / API Secret для канала {expected}",
                user=user,
            )
            continue

        try:
            tx = Transaction.objects.create(
                status="pending",
                paid=False,
                amount=amount_to_charge,
                user=user,
                currency=currency,
                income_info=IncomeInfo.objects.get(pk=1),
                side="Приход средств",
                description=f"Рекуррентный платеж (CloudPayments {label})",
                payment_system=payment_system,
            )
            payload = _charge_payload(user, amount_to_charge, currency, tx.id)
            data, elapsed = _tokens_charge(
                payload, public_id, api_secret, timeout=api_timeout
            )
            ok = bool(data.get("Success"))
            model = data.get("Model") or {}
            cp_tx_id = model.get("TransactionId")
            reason_code = model.get("ReasonCode")

            if ok:
                success += 1
                apply_successful_pay(
                    transaction=tx,
                    telegram_user=user,
                    amount_value=amount_to_charge,
                    payment_id=str(cp_tx_id or tx.id),
                    token=user.cloudpayments_token,
                    channel=expected,
                    log_prefix=f"{prefix}[CELERY] [{label}] [CloudPayments]",
                )
                # Рекуррент ЮKassa ставит +31 от now; apply_successful_pay продлевает от expiration —
                # для expired subscription_status=False extend ставит today+days. OK.
                logger.log(
                    "SUCCESS",
                    f"{prefix}[CELERY] [{label}] Успех за {elapsed:.1f}s user={user.user_id} "
                    f"tx={tx.id} cp={cp_tx_id}",
                    user=user,
                )
            else:
                canceled += 1
                tx.status = "canceled"
                tx.paid = False
                if cp_tx_id:
                    tx.payment_id = str(cp_tx_id)
                tx.save(update_fields=["status", "paid", "payment_id"])
                msg = (
                    f"{prefix}[CELERY] [{label}] Отказ за {elapsed:.1f}s user={user.user_id} "
                    f"ReasonCode={reason_code} Message={data.get('Message')}"
                )
                try:
                    code_int = int(reason_code) if reason_code is not None else None
                except (TypeError, ValueError):
                    code_int = None
                if code_int in REASON_CLEAR_TOKEN:
                    user.cloudpayments_token = ""
                    user.save(update_fields=["cloudpayments_token"])
                    msg += " [токен сброшен]"
                logger.log("WARNING", msg, user=user)

        except Exception as exc:
            failed += 1
            logger.log(
                "FATAL",
                f"{prefix}[CELERY] [{label}] Ошибка user={user.user_id}: {exc}",
                user=user,
            )

    if dry_run:
        summary = f"dry-run: к списанию {len(eligible)} | пропущено {skipped}"
        logger.log("INFO", f"[DRY-RUN] [{label}] [Конец] [{summary}]")
    else:
        summary = (
            f"успешно: {success} | отменено: {canceled} | ошибка: {failed} | пропуск: {skipped}"
        )
        logger.log("INFO", f"[CELERY] [{label}] [Списание] [Конец] [{summary}]")
    return summary


def run_cloudpayments_bot_recurring(logger: TaskRunLogger, *, dry_run=False, api_timeout=DEFAULT_CP_API_TIMEOUT):
    return _run_channel("bot", logger, dry_run=dry_run, api_timeout=api_timeout)


def run_cloudpayments_site_recurring(logger: TaskRunLogger, *, dry_run=False, api_timeout=DEFAULT_CP_API_TIMEOUT):
    return _run_channel("site", logger, dry_run=dry_run, api_timeout=api_timeout)
