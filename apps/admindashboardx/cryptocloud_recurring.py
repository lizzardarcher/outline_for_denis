
"""
Рекуррент CryptoCloud: новый инвойс + ссылка в Telegram.
Подписка продлевается только по POSTBACK, не в этой задаче.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.conf import settings


from apps.payment.subscription_window import renewal_due_q
from apps.payment.cryptocloud_common import (
    create_invoice,
    credentials_for_channel,
    is_cryptocloud_allowed_for_user,
    payment_system_for_channel,
)
from bot.models import IncomeInfo, Prices, TelegramBot, TelegramUser, Transaction

from .task_run_logging import TaskRunLogger


def _user_email(user):
    try:
        return user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
    except Exception:
        return "noemail@noemail.ru"


def _skip_reason(user: TelegramUser, expected_channel: str) -> Optional[str]:
    if user.permission_revoked:
        return "permission_revoked"
    if not is_cryptocloud_allowed_for_user(user):
        return "test-mode: пользователь не в CRYPTOCLOUD_TEST_USERNAMES"
    if not (user.cryptocloud_channel or "").strip():
        return "нет cryptocloud_channel"
    if (getattr(user, "robokassa_recurring_parent_inv_id", "") or "").strip():
        return "активна рекуррентная подписка RoboKassa"
    if (user.payment_method_id or "").strip():
        return "активен payment_method_id ЮKassa"
    if (user.cloudpayments_token or "").strip():
        return "активен cloudpayments_token"
    channel = (user.cryptocloud_channel or "").strip().lower()
    if channel != expected_channel:
        return f"канал «{channel}» (нужен {expected_channel})"
    return None


def _send_pay_link(user: TelegramUser, pay_url: str, amount, logger: TaskRunLogger) -> None:
    from telebot import TeleBot
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    token = TelegramBot.objects.all().first()
    if not token or not token.token:
        raise RuntimeError("Нет TelegramBot.token")
    bot = TeleBot(token=token.token)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f"💳 Оплатить {amount} ₽", url=pay_url))
    if user.subscription_status:
        text = (
            "Подписка заканчивается. Оплатите продление через CryptoCloud — "
            "после оплаты доступ продлится, текущие ключи сохранятся."
        )
    else:
        text = (
            "Подписка истекла. Оплатите продление через CryptoCloud — "
            "после оплаты доступ восстановится автоматически."
        )
    bot.send_message(
        chat_id=user.user_id,
        text=text,
        reply_markup=markup,
    )


def _run_channel(channel: str, logger: TaskRunLogger, *, dry_run=False):
    expected = channel.lower()
    label = channel.upper()
    users = list(
        TelegramUser.objects.filter(
            renewal_due_q(),
            permission_revoked=False,
            cryptocloud_channel__isnull=False,
        ).exclude(cryptocloud_channel="")
    )

    mode = "DRY-RUN" if dry_run else "Инвойс"
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{label}] [CryptoCloud] [{mode}] "
        f"[кандидатов: {len(users)}]",
    )
    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
    currency = getattr(settings, "CRYPTOCLOUD_CURRENCY", "RUB") or "RUB"
    success = failed = skipped = 0

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
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{label}] К инвойсу: {len(eligible)} "
        f"(пропущено: {skipped})",
    )

    api_key, shop_id, _secret = credentials_for_channel(expected)
    payment_system = payment_system_for_channel(expected)

    for idx, user in enumerate(eligible, 1):
        prefix = f"[#{idx:03d}/{len(eligible):03d}] "
        if dry_run:
            logger.log(
                "INFO",
                f"{prefix}[DRY-RUN] [{label}] invoice user={user.user_id} "
                f"amount={amount_to_charge} {currency}",
                user=user,
            )
            continue

        if not api_key or not shop_id:
            failed += 1
            logger.log(
                "FATAL",
                f"{prefix}[{label}] Нет API key / shop_id для канала {expected}",
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
                description=f"Рекуррентный платеж (CryptoCloud {label})",
                payment_system=payment_system,
            )
            invoice = create_invoice(
                channel=expected,
                amount=amount_to_charge,
                order_id=tx.id,
                email=_user_email(user),
            )
            uuid = invoice.get("uuid")
            link = invoice.get("link")
            if uuid:
                tx.payment_id = str(uuid)
                tx.save(update_fields=["payment_id"])
            if not link:
                raise RuntimeError("CryptoCloud: нет link в ответе create invoice")
            _send_pay_link(user, link, amount_to_charge, logger)
            success += 1
            logger.log(
                "SUCCESS",
                f"{prefix}[CELERY] [{label}] Инвойс отправлен user={user.user_id} "
                f"tx={tx.id} uuid={uuid}",
                user=user,
            )
        except Exception as exc:
            failed += 1
            logger.log(
                "FATAL",
                f"{prefix}[CELERY] [{label}] Ошибка user={user.user_id}: {exc}",
                user=user,
            )

    if dry_run:
        summary = f"dry-run: к инвойсу {len(eligible)} | пропущено {skipped}"
        logger.log("INFO", f"[DRY-RUN] [{label}] [Конец] [{summary}]")
    else:
        summary = f"отправлено: {success} | ошибка: {failed} | пропуск: {skipped}"
        logger.log("INFO", f"[CELERY] [{label}] [Инвойс] [Конец] [{summary}]")
    return summary


def run_cryptocloud_bot_recurring(logger: TaskRunLogger, *, dry_run=False):
    return _run_channel("bot", logger, dry_run=dry_run)


def run_cryptocloud_site_recurring(logger: TaskRunLogger, *, dry_run=False):
    return _run_channel("site", logger, dry_run=dry_run)
