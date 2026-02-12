import traceback
from datetime import timedelta, datetime
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from yookassa import Payment, Configuration

from bot.models import TelegramUser, Prices, Logging, Transaction, IncomeInfo, TelegramReferral, ReferralSettings, \
    ReferralTransaction

YOOKASSA_API_BASE = "https://api.yookassa.ru/v3/payments"


@shared_task
def ukassa_bot_attempt_recurring_payment():
    """
    Периодическая задача для списания средств с пользователей,
    у которых статус подписки False и есть payment_method_id.
    """

    users_to_charge = TelegramUser.objects.filter(
        subscription_status=False,
        payment_method_id__isnull=False,
        payment_method_id__gt='',
        permission_revoked=False
    )

    Logging.objects.create(log_level="INFO",
                           message=f'[CELERY] [BOT] [Списание] [Начало] [количество пользователей: {users_to_charge.count()}]',
                           datetime=datetime.now())
    success = 0
    canceled = 0
    failed = 0
    unknown = 0

    for user in users_to_charge:
        if user.payment_method_id.__len__() > 10 and '000' in user.payment_method_id:
            # payment_system = Transaction.objects.filter(payment_id=user.payment_method_id).last().payment_system

            # if payment_system != 'YooKassaBot':
            #     return

            try:
                # Сумма списания
                amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
                currency = 'RUB'

                # Настройка ЮKassa
                Configuration.account_id = settings.YOOKASSA_SHOP_ID_BOT
                Configuration.secret_key = settings.YOOKASSA_SECRET_BOT

                try:
                    email = user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
                except:
                    email = "noemail@noemail.ru"

                payment = Payment.create({
                    "amount": {
                        "value": str(amount_to_charge),
                        "currency": currency
                    },
                    "capture": True,
                    "payment_method_id": user.payment_method_id,
                    "payment_method": {
                        "saved": True
                    },
                    "description": f"Рекуррентный платеж для пользователя {user.user_id} Подписка DomVPN",
                    "receipt": {
                        "customer": {
                            "email": email,
                        },
                        "items": [
                            {
                                "description": "Рекуррентный платеж",
                                "quantity": "1.00",
                                "amount": {
                                    "value": str(amount_to_charge),
                                    "currency": currency
                                },
                                "vat_code": 4,
                                "payment_subject": "service",
                                "payment_mode": "full_payment"
                            }
                        ]
                    }
                })

                if payment.status == 'succeeded':
                    success += 1
                    # Успешный платеж
                    user.subscription_status = True
                    user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                    user.save()
                    Transaction.objects.create(user=user, amount=amount_to_charge, currency=currency,
                                               side='Приход средств', status='succeeded', paid=True,
                                               payment_id=payment.id,
                                               income_info=IncomeInfo.objects.get(pk=1),
                                               description='Рекуррентный платеж',
                                               payment_system='YooKassaBot'
                                               )
                    msg = (
                        f"[CELERY] [BOT] Автосписание успешно! Пользователь {user.user_id} оплатил с {str(amount_to_charge)} {currency}. "
                        f"Подписка активирована до {user.subscription_expiration} ID платежа {user.payment_method_id}"
                    )

                    try:
                        tr = Transaction.objects.filter(payment_id=user.payment_method_id).last()
                        tr.payment_system = 'YooKassaBot'
                        tr.save()
                    except:
                        pass

                    referral_percentages = {
                        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
                    }

                    referred_list = TelegramReferral.objects.filter(referred=user).select_related('referrer')
                    if referred_list:
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
                                income = Decimal(user_to_pay.income) + (
                                        Decimal(amount_to_charge) * Decimal(percent) / 100)
                                user_to_pay.income = income
                                user_to_pay.save()

                    Logging.objects.create(log_level="SUCCESS", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'waiting_for_capture' or payment.status == 'pending':
                    msg = f"[CELERY] [BOT]  Платеж для пользователя {user.user_id} в статусе {payment.status}. Требуется дополнительная проверка."
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'canceled':
                    canceled += 1
                    cancellation_details = payment.cancellation_details
                    reason = cancellation_details.reason if cancellation_details else "Unknown reason"

                    message = f"[CELERY] [BOT]  Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "

                    if reason == 'insufficient_funds':
                        message += "Недостаточно средств для списания. Пополните баланс."

                    elif reason == 'payment_method_restricted':
                        user.payment_method_id = ''
                        user.save()
                        message += "Операции с платежным средством запрещены (карта заблокирована и т.п.). Обратитесь в банк."

                    elif reason == 'permission_revoked':
                        user.payment_method_id = ''
                        user.permission_revoked = True
                        user.save()
                        message += "Вы отозвали разрешение на подписку. Подтвердите подписку заново."

                    elif reason == 'card_expired':
                        user.payment_method_id = ''
                        user.save()
                        message += "Истек срок действия карты. Обновите данные карты."

                    elif reason == 'country_forbidden':
                        user.payment_method_id = ''
                        user.save()
                        message += "Нельзя заплатить банковской картой, выпущенной в этой стране. Используйте другую карту."

                    elif reason == 'fraud_suspected':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж заблокирован из-за подозрения в мошенничестве. Свяжитесь с банком."

                    elif reason == 'issuer_unavailable':
                        user.save()
                        message += "Организация, выпустившая платежное средство, недоступна. Повторите попытку позже."

                    elif reason == 'payment_method_limit_exceeded':
                        user.save()
                        message += "Исчерпан лимит платежей для данного платежного средства или вашего магазина. Повторите попытку позже или используйте другое средство."

                    elif reason == 'invalid_card_number':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан номер карты. Обновите данные карты."

                    elif reason == 'invalid_csc':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан код CVV2 (CVC2, CID). Обновите данные карты."

                    elif reason == 'call_issuer':
                        user.payment_method_id = ''
                        user.save()
                        message += "Оплата отклонена по неизвестным причинам. Обратитесь в банк."

                    elif reason == '3d_secure_failed':
                        user.payment_method_id = ''
                        user.save()
                        message += "Не пройдена аутентификация по 3-D Secure. Повторите попытку, используя другое устройство или обратитесь в банк."

                    elif reason == 'general_decline':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж отклонен. Обратитесь в банк."

                    elif reason == 'expired_on_capture':
                        message += "Истек срок списания оплаты. Повторите попытку."

                    elif reason == 'expired_on_confirmation':
                        message += "Истек срок оплаты: вы не подтвердили платеж. Повторите попытку."

                    elif reason == 'deal_expired':
                        message += "Закончился срок жизни сделки. Создайте новую сделку и повторите оплату."

                    elif reason == 'identification_required':
                        user.payment_method_id = ''
                        user.save()
                        message += "Превышены ограничения на платежи для кошелька ЮMoney. Идентифицируйте кошелек или используйте другое средство."

                    elif reason == 'internal_timeout':
                        message += "Технические неполадки. Повторите попытку позже."

                    elif reason == 'canceled_by_merchant':
                        message += "Платеж отменен. Свяжитесь с поддержкой."

                    else:
                        message += f"Неизвестная причина: {reason}"

                    msg = message
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                else:
                    unknown += 1
                    msg = f"[CELERY] [BOT]  Неизвестный статус платежа {payment.status} для пользователя {user.user_id}."
                    user.payment_method_id = ''
                    user.save()
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

            except Exception as e:
                failed += 1
                msg = f"[CELERY] [BOT]  Ошибка при списании с пользователя {user.user_id}: {e}\nPayment Method ID:{user.payment_method_id}"
                if "This payment_method_id doesn't exist" in msg:
                    user.payment_method_id = ''
                    user.save()
                elif 'Payment method is not available' in msg:
                    user.payment_method_id = ''
                    user.save()
                Logging.objects.create(log_level="FATAL", message=msg, datetime=datetime.now(), user=user)

    Logging.objects.create(
        log_level="INFO",
        message=f"[CELERY] [BOT]  [Списание] [Конец] [успешно: {str(success)} | отменено: {str(canceled)} | ошибка: {str(failed)} | неизвестно: {str(unknown)}]",
        datetime=datetime.now()
    )


@shared_task
def ukassa_site_attempt_recurring_payment():
    """
    Периодическая задача для списания средств с пользователей,
    у которых статус подписки False и есть payment_method_id.
    """

    users_to_charge = TelegramUser.objects.filter(
        subscription_status=False,
        payment_method_id__isnull=False,
        payment_method_id__gt='',
        permission_revoked=False
    )

    Logging.objects.create(log_level="INFO",
                           message=f'[CELERY] [SITE] [Списание] [Начало] [количество пользователей: {users_to_charge.count()}]',
                           datetime=datetime.now())
    success = 0
    canceled = 0
    failed = 0
    unknown = 0

    for user in users_to_charge:
        if user.payment_method_id.__len__() > 10 and '000' in user.payment_method_id:

            # payment_system = Transaction.objects.filter(payment_id=user.payment_method_id).last().payment_system

            # if payment_system != 'YooKassaBot':
            #     return

            try:
                # Сумма списания
                amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
                currency = 'RUB'

                # Настройка ЮKassa
                Configuration.account_id = settings.YOOKASSA_SHOP_ID_SITE
                Configuration.secret_key = settings.YOOKASSA_SECRET_SITE

                try:
                    email = user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
                except:
                    email = "noemail@noemail.ru"

                payment = Payment.create({
                    "amount": {
                        "value": str(amount_to_charge),
                        "currency": currency
                    },
                    "capture": True,
                    "payment_method_id": user.payment_method_id,
                    "payment_method": {
                        "saved": True
                    },
                    "description": f"Рекуррентный платеж для пользователя {user.user_id} Подписка DomVPN",
                    "receipt": {
                        "customer": {
                            "email": email,
                        },
                        "items": [
                            {
                                "description": "Рекуррентный платеж",
                                "quantity": "1.00",
                                "amount": {
                                    "value": str(amount_to_charge),
                                    "currency": currency
                                },
                                "vat_code": 4,
                                "payment_subject": "service",
                                "payment_mode": "full_payment"
                            }
                        ]
                    }
                })

                if payment.status == 'succeeded':
                    success += 1
                    # Успешный платеж
                    user.subscription_status = True
                    user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                    user.save()
                    Transaction.objects.create(user=user, amount=amount_to_charge, currency=currency,
                                               side='Приход средств', status='succeeded', paid=True,
                                               payment_id=payment.id,
                                               income_info=IncomeInfo.objects.get(pk=1),
                                               description='Рекуррентный платеж',
                                               payment_system='YooKassaSite'
                                               )
                    msg = (
                        f"[CELERY] [SITE] Автосписание успешно! Пользователь {user.user_id} оплатил с {str(amount_to_charge)} {currency}. "
                        f"Подписка активирована до {user.subscription_expiration} ID платежа {user.payment_method_id}"
                    )

                    referral_percentages = {
                        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
                    }

                    referred_list = TelegramReferral.objects.filter(referred=user).select_related('referrer')
                    if referred_list:
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
                                income = Decimal(user_to_pay.income) + (
                                        Decimal(amount_to_charge) * Decimal(percent) / 100)
                                user_to_pay.income = income
                                user_to_pay.save()

                    Logging.objects.create(log_level="SUCCESS", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'waiting_for_capture' or payment.status == 'pending':
                    msg = f"[CELERY] [SITE] Платеж для пользователя {user.user_id} в статусе {payment.status}. Требуется дополнительная проверка."
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'canceled':
                    canceled += 1
                    cancellation_details = payment.cancellation_details
                    reason = cancellation_details.reason if cancellation_details else "Unknown reason"

                    message = f"[CELERY] [SITE] Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "

                    if reason == 'insufficient_funds':
                        message += "Недостаточно средств для списания. Пополните баланс."

                    elif reason == 'payment_method_restricted':
                        user.payment_method_id = ''
                        user.save()
                        message += "Операции с платежным средством запрещены (карта заблокирована и т.п.). Обратитесь в банк."

                    elif reason == 'permission_revoked':
                        user.payment_method_id = ''
                        user.permission_revoked = True
                        user.save()
                        message += "Вы отозвали разрешение на подписку. Подтвердите подписку заново."

                    elif reason == 'card_expired':
                        user.payment_method_id = ''
                        user.save()
                        message += "Истек срок действия карты. Обновите данные карты."

                    elif reason == 'country_forbidden':
                        user.payment_method_id = ''
                        user.save()
                        message += "Нельзя заплатить банковской картой, выпущенной в этой стране. Используйте другую карту."

                    elif reason == 'fraud_suspected':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж заблокирован из-за подозрения в мошенничестве. Свяжитесь с банком."

                    elif reason == 'issuer_unavailable':
                        user.save()
                        message += "Организация, выпустившая платежное средство, недоступна. Повторите попытку позже."

                    elif reason == 'payment_method_limit_exceeded':
                        user.save()
                        message += "Исчерпан лимит платежей для данного платежного средства или вашего магазина. Повторите попытку позже или используйте другое средство."

                    elif reason == 'invalid_card_number':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан номер карты. Обновите данные карты."

                    elif reason == 'invalid_csc':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан код CVV2 (CVC2, CID). Обновите данные карты."

                    elif reason == 'call_issuer':
                        user.payment_method_id = ''
                        user.save()
                        message += "Оплата отклонена по неизвестным причинам. Обратитесь в банк."

                    elif reason == '3d_secure_failed':
                        user.payment_method_id = ''
                        user.save()
                        message += "Не пройдена аутентификация по 3-D Secure. Повторите попытку, используя другое устройство или обратитесь в банк."

                    elif reason == 'general_decline':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж отклонен. Обратитесь в банк."

                    elif reason == 'expired_on_capture':
                        message += "Истек срок списания оплаты. Повторите попытку."

                    elif reason == 'expired_on_confirmation':
                        message += "Истек срок оплаты: вы не подтвердили платеж. Повторите попытку."

                    elif reason == 'deal_expired':
                        message += "Закончился срок жизни сделки. Создайте новую сделку и повторите оплату."

                    elif reason == 'identification_required':
                        user.payment_method_id = ''
                        user.save()
                        message += "Превышены ограничения на платежи для кошелька ЮMoney. Идентифицируйте кошелек или используйте другое средство."

                    elif reason == 'internal_timeout':
                        message += "Технические неполадки. Повторите попытку позже."

                    elif reason == 'canceled_by_merchant':
                        message += "Платеж отменен. Свяжитесь с поддержкой."

                    else:
                        message += f"Неизвестная причина: {reason}"

                    msg = message
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                else:
                    unknown += 1
                    msg = f"[CELERY] [SITE] Неизвестный статус платежа {payment.status} для пользователя {user.user_id}."
                    user.payment_method_id = ''
                    user.save()
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

            except Exception as e:
                failed += 1
                msg = f"[CELERY] [SITE] Ошибка при списании с пользователя {user.user_id}: {e}\nPayment Method ID:{user.payment_method_id}"
                if "This payment_method_id doesn't exist" in msg:
                    user.payment_method_id = ''
                    user.save()
                elif 'Payment method is not available' in msg:
                    user.payment_method_id = ''
                    user.save()
                Logging.objects.create(log_level="FATAL", message=msg, datetime=datetime.now(), user=user)

    Logging.objects.create(
        log_level="INFO",
        message=f"[CELERY] [SITE] [Списание] [Конец] [успешно: {str(success)} | отменено: {str(canceled)} | ошибка: {str(failed)} | неизвестно: {str(unknown)}]",
        datetime=datetime.now()
    )


def _fetch_payment_from_yookassa(payment_id: str, shop_id: str, secret_key: str, timeout: int = 10):
    """
    Получает данные платежа через HTTP API ЮKassa.
    Возвращает dict (payment data) при 200 или None при 404/ошибке аутентификации/другой ошибке.
    """
    try:
        resp = requests.get(f"{YOOKASSA_API_BASE}/{payment_id}", auth=(shop_id, secret_key), timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        # 404 - платёж не найден (возможно в другом магазине) -> пропускаем
        return None
    except Exception:
        return None


def _process_payment_data(payment_data: dict, transaction: Transaction, telegram_user: TelegramUser, source_label: str):
    """
    Общая логика обработки payment_data как в вебхуках: succeeded/canceled.
    source_label - 'BOT' или 'WEB' для логов.
    """
    try:
        event_status = payment_data.get("status", "")

        # Получаем сумму
        amount_value = None
        try:
            amount_value = float(payment_data.get("amount", {}).get("value", 0))
        except Exception:
            amount_value = 0.0

        if "succeeded" in str(event_status):
            Logging.objects.create(log_level="SUCCESS",
                                   message=f'[{source_label}] [Приём опроса] [succeeded] [payment_id={transaction.payment_id}]',
                                   datetime=timezone.now())
            # Защита от повторной обработки
            if transaction.status != "succeeded" and int(amount_value) > 0:
                transaction.status = event_status
                transaction.paid = True
                transaction.save()

                # Определяем дни подписки по сумме
                days = 0
                try:
                    prices = Prices.objects.get(id=1)
                    if int(amount_value) == int(prices.price_1):
                        days = 31
                    elif int(amount_value) == int(prices.price_2):
                        days = 93
                    elif int(amount_value) == int(prices.price_3):
                        days = 184
                    elif int(amount_value) == int(prices.price_4):
                        days = 366
                    elif int(amount_value) == int(prices.price_5):
                        days = 3
                except Exception:
                    # Если с Prices что-то не так — оставить days = 0
                    pass

                payment_method_id = None
                try:
                    payment_method = payment_data.get("payment_method") or {}
                    payment_method_id = payment_method.get("id")
                except Exception:
                    payment_method_id = None

                # Обновляем подписку пользователя
                if telegram_user:
                    if getattr(telegram_user, "subscription_status", False):
                        # если поле subscription_expiration пустое, используем сейчас
                        if not getattr(telegram_user, "subscription_expiration", None):
                            telegram_user.subscription_expiration = timezone.now()
                        telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(
                            days=days)
                        if payment_method_id:
                            telegram_user.payment_method_id = payment_method_id
                        telegram_user.permission_revoked = False
                        telegram_user.save()
                    else:
                        telegram_user.subscription_status = True
                        telegram_user.subscription_expiration = timezone.now() + timedelta(days=days)
                        if payment_method_id:
                            telegram_user.payment_method_id = payment_method_id
                        telegram_user.permission_revoked = False
                        telegram_user.save()

                Logging.objects.create(log_level="INFO",
                                       message=f'[{source_label}] [Обработка платежа] [payment_id={transaction.payment_id}] [Сумма: {amount_value}] [Дни: {days}]',
                                       datetime=timezone.now(), user=telegram_user)

                # Реферальные начисления
                try:
                    referral_percentages = {
                        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
                    }
                except Exception:
                    referral_percentages = {}

                try:
                    referred_list = TelegramReferral.objects.filter(referred=telegram_user).select_related('referrer')
                except Exception:
                    referred_list = []

                if referred_list:
                    user_ids_to_pay = [r.referrer.user_id for r in referred_list if r.referrer]
                    users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}

                    for r in referred_list:
                        level = r.level
                        user_to_pay = users_to_pay.get(r.referrer.user_id) if r.referrer else None
                        if not user_to_pay:
                            continue

                        percent = referral_percentages.get(level)

                        # special_offer override
                        if getattr(user_to_pay, "special_offer", None):
                            try:
                                so = user_to_pay.special_offer
                                referral_percentages_2 = {
                                    1: so.level_1_percentage,
                                    2: so.level_2_percentage,
                                    3: so.level_3_percentage,
                                    4: so.level_4_percentage,
                                    5: so.level_5_percentage,
                                }
                                percent = referral_percentages_2.get(level)
                            except Exception:
                                pass

                        if percent:
                            try:
                                income_new = Decimal(user_to_pay.income) + (
                                            Decimal(amount_value) * Decimal(percent) / 100)
                                user_to_pay.income = income_new
                                user_to_pay.save()
                                ReferralTransaction.objects.create(
                                    referral=r,
                                    amount=(Decimal(amount_value) * Decimal(percent) / 100),
                                    transaction=transaction
                                )
                            except Exception:
                                # не критично, просто логируем
                                Logging.objects.create(log_level="DANGER",
                                                       message=f'[{source_label}] [Ошибка реферальной выплаты] [payment_id={transaction.payment_id}] [{traceback.format_exc()}]',
                                                       datetime=timezone.now(), user=telegram_user)

                Logging.objects.create(log_level="SUCCESS",
                                       message=f'[{source_label}] [Платёж на сумму {str(amount_value)} р. прошёл] [payment_id={transaction.payment_id}]',
                                       datetime=timezone.now(), user=telegram_user)

        elif "canceled" in str(event_status):
            Logging.objects.create(log_level="WARNING",
                                   message=f'[{source_label}] [Приём опроса] [canceled] [payment_id={transaction.payment_id}]',
                                   datetime=timezone.now())
            try:
                transaction.status = event_status
                transaction.paid = False
                transaction.save()
            except Exception:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[{source_label}] [Ошибка при обработке canceled] [payment_id={transaction.payment_id}] [{traceback.format_exc()}]',
                                       datetime=timezone.now(), user=telegram_user)
        else:
            Logging.objects.create(log_level="DANGER",
                                   message=f'[{source_label}] [Неизвестный статус при опросе] [status={event_status}] [payment_id={transaction.payment_id}]',
                                   datetime=timezone.now())
    except Exception:
        Logging.objects.create(log_level="DANGER", message=f'{traceback.format_exc()}', datetime=timezone.now())


@shared_task(bind=True, name="yookassa_check_pending_bot")
def ukassa_check_pending_bot(self):
    """
    Таск для опроса платежей ЮKassa (бот). Проходит по всем pending Transaction и пытается получить
    статус платежа, используя креды бота. Если платёж найден — обрабатывает (succeeded/canceled).
    """
    shop_id = getattr(settings, "YOOKASSA_SHOP_ID_BOT", None)
    secret = getattr(settings, "YOOKASSA_SECRET_BOT", None)
    if not shop_id or not secret:
        Logging.objects.create(log_level="DANGER", message='[BOT] YOOKASSA credentials not configured',
                               datetime=timezone.now())
        return

    pending_qs = Transaction.objects.filter(status="pending", paid=False, payment_id__isnull=False,
                                            timestamp__gte=datetime.now() - timedelta(days=1),
                                            payment_system='YooKassaBot').select_related('user')

    for transaction in pending_qs:
        try:
            payment_id = transaction.payment_id
            if not payment_id:
                continue
            payment_data = _fetch_payment_from_yookassa(payment_id, shop_id, secret)
            if not payment_data:
                # платёж не найден под этим магазином -> пропускаем
                continue

            # получаем telegram_user (у вас в модели Transaction user это TelegramUser уже)
            telegram_user = transaction.user if isinstance(transaction.user, TelegramUser) else None
            _process_payment_data(payment_data, transaction, telegram_user, source_label="BOT")
        except Exception:
            Logging.objects.create(log_level="DANGER",
                                   message=f'[BOT] [Ошибка при опросе платежа {str(traceback.format_exc())}] [payment_id={getattr(transaction, "payment_id", None)}]',
                                   datetime=timezone.now())


@shared_task(bind=True, name="yookassa_check_pending_site")
def ukassa_check_pending_site(self):
    """
    Таск для опроса платежей ЮKassa (сайт). Аналогично таску для бота, но использует креды сайта.
    """
    shop_id = getattr(settings, "YOOKASSA_SHOP_ID_SITE", None)
    secret = getattr(settings, "YOOKASSA_SECRET_SITE", None)
    if not shop_id or not secret:
        Logging.objects.create(log_level="DANGER", message='[WEB] YOOKASSA credentials not configured',
                               datetime=timezone.now())
        return

    pending_qs = Transaction.objects.filter(status="pending", paid=False, payment_id__isnull=False,
                                            timestamp__gte=datetime.now() - timedelta(days=1),
                                            payment_system='YooKassaSite'
                                            ).select_related('user')
    for transaction in pending_qs:
        try:
            payment_id = transaction.payment_id
            if not payment_id:
                continue
            payment_data = _fetch_payment_from_yookassa(payment_id, shop_id, secret)
            if not payment_data:
                continue

            telegram_user = transaction.user if isinstance(transaction.user, TelegramUser) else None
            _process_payment_data(payment_data, transaction, telegram_user, source_label="WEB")
        except Exception:
            Logging.objects.create(log_level="DANGER",
                                   message=f'[WEB] [Ошибка при опросе платежа {str(traceback.format_exc())}] [payment_id={getattr(transaction, "payment_id", None)}]',
                                   datetime=timezone.now())
