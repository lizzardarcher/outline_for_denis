import time
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import requests
from django.conf import settings
from django.utils import timezone

from bot.models import (
    IncomeInfo,
    Prices,
    ReferralSettings,
    TelegramReferral,
    TelegramUser,
    Transaction,
)

from .task_run_logging import TaskRunLogger


YOOKASSA_API_BASE = "https://api.yookassa.ru/v3/payments"
DEFAULT_YOOKASSA_API_TIMEOUT = 30


class _YooKassaPaymentResponse:
    def __init__(self, data):
        self.id = data.get("id")
        self.status = data.get("status")
        cancellation = data.get("cancellation_details") or {}
        self.cancellation_details = (
            SimpleNamespace(reason=cancellation.get("reason")) if cancellation else None
        )


def _build_payment_system_map(users):
    """Последняя payment_system по payment_method_id (один запрос вместо N)."""
    pm_ids = [u.payment_method_id for u in users if u.payment_method_id]
    if not pm_ids:
        return {}
    rows = (
        Transaction.objects.filter(payment_id__in=pm_ids)
        .order_by("payment_id", "-id")
        .values_list("payment_id", "payment_system")
    )
    result = {}
    for payment_id, payment_system in rows:
        if payment_id not in result:
            result[payment_id] = payment_system
    return result


def _payment_system_for_user(user, payment_system_by_pm_id):
    if payment_system_by_pm_id is not None:
        return payment_system_by_pm_id.get(user.payment_method_id)
    try:
        return Transaction.objects.filter(payment_id=user.payment_method_id).last().payment_system
    except (Transaction.DoesNotExist, AttributeError):
        return None


def _create_yookassa_payment(
    payload,
    shop_id,
    secret_key,
    *,
    timeout,
    logger,
    prefix,
    channel,
    user,
):
    logger.log(
        "INFO",
        f"{prefix}[{channel}] Запрос YooKassa Payment.create (timeout={timeout}s)...",
        user=user,
    )
    started = time.monotonic()
    try:
        response = requests.post(
            YOOKASSA_API_BASE,
            json=payload,
            auth=(shop_id, secret_key),
            headers={
                "Idempotence-Key": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        elapsed = time.monotonic() - started
        raise TimeoutError(
            f"YooKassa API: таймаут {timeout}s (ожидание {elapsed:.1f}s)"
        ) from exc
    except requests.RequestException as exc:
        elapsed = time.monotonic() - started
        raise RuntimeError(f"YooKassa API: ошибка сети за {elapsed:.1f}s: {exc}") from exc

    elapsed = time.monotonic() - started
    logger.log(
        "INFO",
        f"{prefix}[{channel}] Ответ YooKassa за {elapsed:.1f}s, HTTP {response.status_code}",
        user=user,
    )
    if not response.ok:
        body_preview = (response.text or "")[:300]
        raise RuntimeError(
            f"YooKassa API: HTTP {response.status_code}, тело: {body_preview}"
        )

    data = response.json()
    logger.log(
        "INFO",
        f"{prefix}[{channel}] payment_id={data.get('id')}, status={data.get('status')}",
        user=user,
    )
    return _YooKassaPaymentResponse(data)


def _recurring_payment_payload(user, amount_to_charge, currency):
    return {
        "amount": {"value": str(amount_to_charge), "currency": currency},
        "capture": True,
        "payment_method_id": user.payment_method_id,
        "payment_method": {"saved": True},
        "description": f"Рекуррентный платеж для пользователя {user.user_id} Подписка DomVPN",
        "receipt": {
            "customer": {"email": _user_email(user)},
            "items": [
                {
                    "description": "Рекуррентный платеж",
                    "quantity": "1.00",
                    "amount": {"value": str(amount_to_charge), "currency": currency},
                    "vat_code": 4,
                    "payment_subject": "service",
                    "payment_mode": "full_payment",
                }
            ],
        },
    }


def _apply_cancellation_side_effects(user, reason):
    """Обновляет пользователя по причине отмены платежа. Возвращает доп. текст сообщения."""
    if reason == "insufficient_funds":
        return "Недостаточно средств для списания. Пополните баланс."

    if reason == "payment_method_restricted":
        user.payment_method_id = ""
        user.save()
        return "Операции с платежным средством запрещены (карта заблокирована и т.п.). Обратитесь в банк."

    if reason == "permission_revoked":
        user.payment_method_id = ""
        user.permission_revoked = True
        user.save()
        return "Вы отозвали разрешение на подписку. Подтвердите подписку заново."

    if reason == "card_expired":
        user.payment_method_id = ""
        user.save()
        return "Истек срок действия карты. Обновите данные карты."

    if reason == "country_forbidden":
        user.payment_method_id = ""
        user.save()
        return "Нельзя заплатить банковской картой, выпущенной в этой стране. Используйте другую карту."

    if reason == "fraud_suspected":
        user.payment_method_id = ""
        user.save()
        return "Платеж заблокирован из-за подозрения в мошенничестве. Свяжитесь с банком."

    if reason == "issuer_unavailable":
        user.save()
        return "Организация, выпустившая платежное средство, недоступна. Повторите попытку позже."

    if reason == "payment_method_limit_exceeded":
        user.save()
        return (
            "Исчерпан лимит платежей для данного платежного средства или вашего магазина. "
            "Повторите попытку позже или используйте другое средство."
        )

    if reason == "invalid_card_number":
        user.payment_method_id = ""
        user.save()
        return "Неправильно указан номер карты. Обновите данные карты."

    if reason == "invalid_csc":
        user.payment_method_id = ""
        user.save()
        return "Неправильно указан код CVV2 (CVC2, CID). Обновите данные карты."

    if reason == "call_issuer":
        user.payment_method_id = ""
        user.save()
        return "Оплата отклонена по неизвестным причинам. Обратитесь в банк."

    if reason == "3d_secure_failed":
        user.payment_method_id = ""
        user.save()
        return (
            "Не пройдена аутентификация по 3-D Secure. Повторите попытку, "
            "используя другое устройство или обратитесь в банк."
        )

    if reason == "general_decline":
        user.payment_method_id = ""
        user.save()
        return "Платеж отклонен. Обратитесь в банк."

    if reason == "expired_on_capture":
        return "Истек срок списания оплаты. Повторите попытку."

    if reason == "expired_on_confirmation":
        return "Истек срок оплаты: вы не подтвердили платеж. Повторите попытку."

    if reason == "deal_expired":
        return "Закончился срок жизни сделки. Создайте новую сделку и повторите оплату."

    if reason == "identification_required":
        user.payment_method_id = ""
        user.save()
        return (
            "Превышены ограничения на платежи для кошелька ЮMoney. "
            "Идентифицируйте кошелек или используйте другое средство."
        )

    if reason == "internal_timeout":
        return "Технические неполадки. Повторите попытку позже."

    if reason == "canceled_by_merchant":
        return "Платеж отменен. Свяжитесь с поддержкой."

    return f"Неизвестная причина: {reason}"


def _apply_referral_income(user, amount_to_charge):
    referral_percentages = {
        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
    }

    referred_list = TelegramReferral.objects.filter(referred=user).select_related("referrer")
    if not referred_list:
        return

    user_ids_to_pay = [r.referrer.user_id for r in referred_list]
    users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}

    for r in referred_list:
        level = r.level
        user_to_pay = users_to_pay.get(r.referrer.user_id)
        if not user_to_pay:
            continue
        percent = referral_percentages.get(level)
        if user_to_pay.special_offer:
            referral_percentages_2 = {
                1: user_to_pay.special_offer.level_1_percentage,
                2: user_to_pay.special_offer.level_2_percentage,
                3: user_to_pay.special_offer.level_3_percentage,
                4: user_to_pay.special_offer.level_4_percentage,
                5: user_to_pay.special_offer.level_5_percentage,
            }
            percent = referral_percentages_2.get(level)
        if percent:
            income = Decimal(user_to_pay.income) + (Decimal(amount_to_charge) * Decimal(percent) / 100)
            user_to_pay.income = income
            user_to_pay.save()


def _user_email(user):
    try:
        return user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
    except Exception:
        return "noemail@noemail.ru"


def _handle_payment_exception(user, exc, channel, logger: TaskRunLogger, *, dry_run=False, prefix=""):
    msg = (
        f"{prefix}[CELERY] [{channel}] Ошибка при списании с пользователя {user.user_id}: {exc}\n"
        f"Payment Method ID:{user.payment_method_id}"
    )
    if not dry_run:
        if "This payment_method_id doesn't exist" in msg or "Payment method is not available" in msg:
            user.payment_method_id = ""
            user.save()
    logger.log("FATAL", msg, user=user)
    return 1


def _charge_step_prefix(index, total):
    return f"[#{index:03d}/{total:03d}]"


def _bot_skip_reason(user, payment_system_by_pm_id=None):
    if (getattr(user, "robokassa_recurring_parent_inv_id", "") or "").strip():
        return "активна рекуррентная подписка RoboKassa"
    if not (len(user.payment_method_id) > 10 and "000" in user.payment_method_id):
        return "payment_method_id не подходит под YooKassa Bot"
    payment_system = _payment_system_for_user(user, payment_system_by_pm_id)
    if payment_system in ("YooKassaSite", "RoboKassaBot", "RoboKassaSite"):
        return f"платёжная система «{payment_system}» (не Bot)"
    return None


def _site_skip_reason(user, payment_system_by_pm_id=None):
    if not user.payment_method_id:
        return "нет payment_method_id"
    payment_system = _payment_system_for_user(user, payment_system_by_pm_id)
    if payment_system != "YooKassaSite":
        ps = payment_system or "неизвестна"
        return f"платёжная система «{ps}» (нужна YooKassaSite)"
    return None


def _dry_run_charge_log(channel, user, amount_to_charge, currency, payment_system_label, prefix=""):
    exp_date = timezone.now().date() + timedelta(days=31)
    referral_count = TelegramReferral.objects.filter(referred=user).count()
    pm_preview = user.payment_method_id[:12] + "…" if len(user.payment_method_id) > 12 else user.payment_method_id
    return (
        f"{prefix}[DRY-RUN] [{channel}] Списание: user_id={user.user_id}, сумма={amount_to_charge} {currency}, "
        f"email={_user_email(user)}, payment_method_id={pm_preview}, магазин={payment_system_label}. "
        f"Будет: Payment.create → при успехе подписка до {exp_date}, Transaction ({payment_system_label}), "
        f"рефералов для начисления: {referral_count}"
    )


def run_ukassa_bot_recurring(
    logger: TaskRunLogger,
    *,
    dry_run=False,
    api_timeout=DEFAULT_YOOKASSA_API_TIMEOUT,
):
    channel = "BOT"
    users_to_charge = list(
        TelegramUser.objects.filter(
            subscription_status=False,
            payment_method_id__isnull=False,
            payment_method_id__gt="",
            permission_revoked=False,
        )
    )
    payment_system_by_pm_id = _build_payment_system_map(users_to_charge)

    mode_label = "DRY-RUN" if dry_run else "Списание"
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{channel}] [{mode_label}] [Начало] "
        f"[кандидатов в выборке: {len(users_to_charge)}]",
    )
    if dry_run:
        logger.log(
            "WARNING",
            "[DRY-RUN] Режим пробного запуска — запросы в YooKassa и изменения в БД не выполняются.",
        )

    success = canceled = failed = unknown = skipped = 0
    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
    currency = "RUB"

    eligible_users = []
    for user in users_to_charge:
        skip_reason = _bot_skip_reason(user, payment_system_by_pm_id)
        if skip_reason:
            skipped += 1
            if dry_run:
                logger.log(
                    "DEBUG",
                    f"[DRY-RUN] [{channel}] Пропуск user_id={user.user_id}: {skip_reason}",
                    user=user,
                )
            continue
        eligible_users.append(user)

    total_charges = len(eligible_users)
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{channel}] К списанию: {total_charges} "
        f"(пропущено: {skipped})",
    )

    for idx, user in enumerate(eligible_users, 1):
        prefix = f"{_charge_step_prefix(idx, total_charges)} "
        logger.log(
            "INFO",
            f"{prefix}[{channel}] Попытка списания user_id={user.user_id}, сумма={amount_to_charge} {currency}",
            user=user,
        )

        if dry_run:
            logger.log(
                "INFO",
                _dry_run_charge_log(
                    channel, user, amount_to_charge, currency, "YooKassa Bot", prefix=prefix
                ),
                user=user,
            )
            continue

        try:
            payment = _create_yookassa_payment(
                _recurring_payment_payload(user, amount_to_charge, currency),
                settings.YOOKASSA_SHOP_ID_BOT,
                settings.YOOKASSA_SECRET_BOT,
                timeout=api_timeout,
                logger=logger,
                prefix=prefix,
                channel=channel,
                user=user,
            )

            if payment.status == "succeeded":
                success += 1
                user.subscription_status = True
                user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                user.save()
                Transaction.objects.create(
                    user=user,
                    amount=amount_to_charge,
                    currency=currency,
                    side="Приход средств",
                    status="succeeded",
                    paid=True,
                    payment_id=payment.id,
                    income_info=IncomeInfo.objects.get(pk=1),
                    description="Рекуррентный платеж",
                    payment_system="YooKassaBot",
                )
                msg = (
                    f"{prefix}[CELERY] [{channel}] Автосписание успешно! Пользователь {user.user_id} оплатил "
                    f"с {amount_to_charge} {currency}. Подписка активирована до {user.subscription_expiration} "
                    f"ID платежа {user.payment_method_id}"
                )
                try:
                    tr = Transaction.objects.filter(payment_id=user.payment_method_id).last()
                    tr.payment_system = "YooKassaBot"
                    tr.save()
                except Exception:
                    pass
                _apply_referral_income(user, amount_to_charge)
                logger.log("SUCCESS", msg, user=user)

            elif payment.status in ("waiting_for_capture", "pending"):
                msg = (
                    f"{prefix}[CELERY] [{channel}] Платеж для пользователя {user.user_id} в статусе {payment.status}. "
                    "Требуется дополнительная проверка."
                )
                logger.log("WARNING", msg, user=user)

            elif payment.status == "canceled":
                canceled += 1
                cancellation_details = payment.cancellation_details
                reason = cancellation_details.reason if cancellation_details else "Unknown reason"
                message = f"{prefix}[CELERY] [{channel}] Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "
                message += _apply_cancellation_side_effects(user, reason)
                logger.log("WARNING", message, user=user)

            else:
                unknown += 1
                msg = (
                    f"{prefix}[CELERY] [{channel}] Неизвестный статус платежа {payment.status} "
                    f"для пользователя {user.user_id}."
                )
                user.payment_method_id = ""
                user.save()
                logger.log("WARNING", msg, user=user)

        except Exception as exc:
            failed += _handle_payment_exception(
                user, exc, channel, logger, dry_run=dry_run, prefix=prefix
            )

    if dry_run:
        summary = f"dry-run: к списанию {total_charges} | пропущено {skipped}"
        logger.log("INFO", f"[DRY-RUN] [{channel}] [Конец] [{summary}]")
    else:
        summary = (
            f"успешно: {success} | отменено: {canceled} | ошибка: {failed} | неизвестно: {unknown}"
        )
        logger.log("INFO", f"[CELERY] [{channel}] [Списание] [Конец] [{summary}]")
    return summary


def run_ukassa_site_recurring(
    logger: TaskRunLogger,
    *,
    dry_run=False,
    api_timeout=DEFAULT_YOOKASSA_API_TIMEOUT,
):
    channel = "SITE"
    users_to_charge = list(
        TelegramUser.objects.filter(
            subscription_status=False,
            payment_method_id__isnull=False,
            payment_method_id__gt="",
            permission_revoked=False,
        )
    )
    payment_system_by_pm_id = _build_payment_system_map(users_to_charge)


    mode_label = "DRY-RUN" if dry_run else "Списание"
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{channel}] [{mode_label}] [Начало] "
        f"[кандидатов в выборке: {len(users_to_charge)}]",
    )
    if dry_run:
        logger.log(
            "WARNING",
            "[DRY-RUN] Режим пробного запуска — запросы в YooKassa и изменения в БД не выполняются.",
        )

    success = canceled = failed = unknown = skipped = 0
    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
    currency = "RUB"

    eligible_users = []
    for user in users_to_charge:
        skip_reason = _site_skip_reason(user, payment_system_by_pm_id)
        if skip_reason:
            skipped += 1
            if dry_run:
                logger.log(
                    "DEBUG",
                    f"[DRY-RUN] [{channel}] Пропуск user_id={user.user_id}: {skip_reason}",
                    user=user,
                )
            continue
        eligible_users.append(user)

    total_charges = len(eligible_users)
    logger.log(
        "INFO",
        f"[{'DRY-RUN' if dry_run else 'CELERY'}] [{channel}] К списанию: {total_charges} "
        f"(пропущено: {skipped})",
    )

    for idx, user in enumerate(eligible_users, 1):
        prefix = f"{_charge_step_prefix(idx, total_charges)} "
        logger.log(
            "INFO",
            f"{prefix}[{channel}] Попытка списания user_id={user.user_id}, сумма={amount_to_charge} {currency}",
            user=user,
        )

        if dry_run:
            logger.log(
                "INFO",
                _dry_run_charge_log(
                    channel, user, amount_to_charge, currency, "YooKassa Site", prefix=prefix
                ),
                user=user,
            )
            continue

        try:
            payment = _create_yookassa_payment(
                _recurring_payment_payload(user, amount_to_charge, currency),
                settings.YOOKASSA_SHOP_ID_SITE,
                settings.YOOKASSA_SECRET_SITE,
                timeout=api_timeout,
                logger=logger,
                prefix=prefix,
                channel=channel,
                user=user,
            )

            if payment.status == "succeeded":
                success += 1
                user.subscription_status = True
                user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                user.save()
                Transaction.objects.create(
                    user=user,
                    amount=amount_to_charge,
                    currency=currency,
                    side="Приход средств",
                    status="succeeded",
                    paid=True,
                    payment_id=payment.id,
                    income_info=IncomeInfo.objects.get(pk=1),
                    description="Рекуррентный платеж",
                    payment_system="YooKassaSite",
                )
                msg = (
                    f"{prefix}[CELERY] [{channel}] Автосписание успешно! Пользователь {user.user_id} оплатил "
                    f"с {amount_to_charge} {currency}. Подписка активирована до {user.subscription_expiration} "
                    f"ID платежа {user.payment_method_id}"
                )
                _apply_referral_income(user, amount_to_charge)
                logger.log("SUCCESS", msg, user=user)

            elif payment.status in ("waiting_for_capture", "pending"):
                msg = (
                    f"{prefix}[CELERY] [{channel}] Платеж для пользователя {user.user_id} в статусе {payment.status}. "
                    "Требуется дополнительная проверка."
                )
                logger.log("WARNING", msg, user=user)

            elif payment.status == "canceled":
                canceled += 1
                cancellation_details = payment.cancellation_details
                reason = cancellation_details.reason if cancellation_details else "Unknown reason"
                message = f"{prefix}[CELERY] [{channel}] Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "
                message += _apply_cancellation_side_effects(user, reason)
                logger.log("WARNING", message, user=user)

            else:
                unknown += 1
                msg = (
                    f"{prefix}[CELERY] [{channel}] Неизвестный статус платежа {payment.status} "
                    f"для пользователя {user.user_id}."
                )
                user.payment_method_id = ""
                user.save()
                logger.log("WARNING", msg, user=user)

        except Exception as exc:
            failed += _handle_payment_exception(
                user, exc, channel, logger, dry_run=dry_run, prefix=prefix
            )

    if dry_run:
        summary = f"dry-run: к списанию {total_charges} | пропущено {skipped}"
        logger.log("INFO", f"[DRY-RUN] [{channel}] [Конец] [{summary}]")
    else:
        summary = (
            f"успешно: {success} | отменено: {canceled} | ошибка: {failed} | неизвестно: {unknown}"
        )
        logger.log("INFO", f"[CELERY] [{channel}] [Списание] [Конец] [{summary}]")
    return summary
