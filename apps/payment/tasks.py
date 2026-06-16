import json
import traceback
import urllib
from datetime import timedelta, datetime
from decimal import Decimal
import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from yookassa import Payment, Configuration

from bot.models import TelegramUser, Prices, Logging, Transaction, IncomeInfo, TelegramReferral, ReferralSettings, \
    ReferralTransaction

YOOKASSA_API_BASE = "https://api.yookassa.ru/v3/payments"


### YooKassa
@shared_task
def ukassa_bot_attempt_recurring_payment():
    """Периодическая задача — логика в apps.admindashboardx.ukassa_recurring."""
    from apps.admindashboardx.task_run_logging import TaskRunLogger
    from apps.admindashboardx.ukassa_recurring import run_ukassa_bot_recurring

    return run_ukassa_bot_recurring(TaskRunLogger(channel="BOT"))


@shared_task
def ukassa_site_attempt_recurring_payment():
    """Периодическая задача — логика в apps.admindashboardx.ukassa_recurring."""
    from apps.admindashboardx.task_run_logging import TaskRunLogger
    from apps.admindashboardx.ukassa_recurring import run_ukassa_site_recurring

    return run_ukassa_site_recurring(TaskRunLogger(channel="SITE"))


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


def _process_payment_data(payment_data: dict, transaction: Transaction, telegram_user: TelegramUser,
                          source_label: str):
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
            Logging.objects.create(category="payment", log_level="SUCCESS",
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

                Logging.objects.create(category="payment", log_level="INFO",
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
                    referred_list = TelegramReferral.objects.filter(referred=telegram_user).select_related(
                        'referrer')
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
                                Logging.objects.create(category="payment", log_level="DANGER",
                                                       message=f'[{source_label}] [Ошибка реферальной выплаты] [payment_id={transaction.payment_id}] [{traceback.format_exc()}]',
                                                       datetime=timezone.now(), user=telegram_user)

                Logging.objects.create(category="payment", log_level="SUCCESS",
                                       message=f'[{source_label}] [Платёж на сумму {str(amount_value)} р. прошёл] [payment_id={transaction.payment_id}]',
                                       datetime=timezone.now(), user=telegram_user)

        elif "canceled" in str(event_status):
            Logging.objects.create(category="payment", log_level="WARNING",
                                   message=f'[{source_label}] [Приём опроса] [canceled] [payment_id={transaction.payment_id}]',
                                   datetime=timezone.now())
            try:
                transaction.status = event_status
                transaction.paid = False
                transaction.save()
            except Exception:
                Logging.objects.create(category="payment", log_level="DANGER",
                                       message=f'[{source_label}] [Ошибка при обработке canceled] [payment_id={transaction.payment_id}] [{traceback.format_exc()}]',
                                       datetime=timezone.now(), user=telegram_user)
        else:
            Logging.objects.create(category="payment", log_level="DANGER",
                                   message=f'[{source_label}] [Неизвестный статус при опросе] [status={event_status}] [payment_id={transaction.payment_id}]',
                                   datetime=timezone.now())
    except Exception:
        Logging.objects.create(category="payment", log_level="DANGER", message=f'{traceback.format_exc()}', datetime=timezone.now())


@shared_task(bind=True, name="yookassa_check_pending_bot")
def ukassa_check_pending_bot(self):
    """
    Таск для опроса платежей ЮKassa (бот). Проходит по всем pending Transaction и пытается получить
    статус платежа, используя креды бота. Если платёж найден — обрабатывает (succeeded/canceled).
    """
    shop_id = getattr(settings, "YOOKASSA_SHOP_ID_BOT", None)
    secret = getattr(settings, "YOOKASSA_SECRET_BOT", None)
    if not shop_id or not secret:
        Logging.objects.create(category="payment", log_level="DANGER", message='[BOT] YOOKASSA credentials not configured',
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
            Logging.objects.create(category="payment", log_level="DANGER",
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
        Logging.objects.create(category="payment", log_level="DANGER", message='[WEB] YOOKASSA credentials not configured',
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
            Logging.objects.create(category="payment", log_level="DANGER",
                                   message=f'[WEB] [Ошибка при опросе платежа {str(traceback.format_exc())}] [payment_id={getattr(transaction, "payment_id", None)}]',
                                   datetime=timezone.now())


### RoboKassa

ROBOKASSA_RECURRING_URL = 'https://auth.robokassa.ru/Merchant/Recurring'
ROBOKASSA_OPSTATE_URL = 'https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpState'


def robokassa_md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest().upper()


def post_robokassa_bot_recurring_invoice(*, merchant_login: str, password_1: str, invoice_id: int,
                                         previous_invoice_id: str, out_sum: Decimal, description: str,
                                         is_test: bool) -> tuple[bool, str]:
    """
    Отправка рекуррентного платежа в Робокассу с чеком по 54-ФЗ.

    Receipt ВХОДИТ В ПОДПИСЬ [web:31]:
    Подпись: MD5(MerchantLogin:OutSum:InvId:Receipt:Password1)
    Receipt нужно URL-кодировать ПЕРЕД добавлением в строку для подписи [web:31].
    """
    out_sum_str = f'{out_sum:.2f}'

    receipt = {
        "sno": "usn_income",
        "items": [
            {
                "name": (description or "Услуга DomVPN")[:100],
                "quantity": 1,
                "sum": float(out_sum),  # в рублях [web:31]
                "payment_method": "full_payment",
                "payment_object": "service",
                "tax": "vat0"
            }
        ]
    }

    import urllib.parse

    # Receipt URL-кодировать ПЕРЕД добавлением в строку для подписи [web:31]
    receipt_json = json.dumps(receipt, ensure_ascii=False)
    receipt_encoded = urllib.parse.quote(receipt_json, safe='')

    # Подпись с Receipt [web:31]: MerchantLogin:OutSum:InvId:Receipt:Password1
    signature = robokassa_md5(f'{merchant_login}:{out_sum_str}:{invoice_id}:{receipt_encoded}:{password_1}')

    data = {
        'MerchantLogin': merchant_login,
        'InvoiceID': str(invoice_id),
        'PreviousInvoiceID': str(previous_invoice_id),
        'OutSum': out_sum_str,
        'Description': (description or 'Услуга DomVPN')[:100],
        'SignatureValue': signature,
        'Receipt': receipt_encoded,  # URL-кодированный Receipt [web:31]
    }

    if is_test:
        data['IsTest'] = '1'

    resp = requests.post(ROBOKASSA_RECURRING_URL, data=data, timeout=60)
    text = (resp.text or '').strip()
    ok = resp.ok and text.upper().startswith('OK')
    return ok, text


def _fetch_robokassa_payment_info(inv_id: str, merchant_login: str, password_2: str):
    signature = robokassa_md5(f"{merchant_login}:{inv_id}:{password_2}")
    params = {
        "MerchantLogin": merchant_login,
        "InvoiceID": inv_id,
        "Signature": signature,
    }
    try:
        resp = requests.get(ROBOKASSA_OPSTATE_URL, params=params, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        result = {}
        for child in root:
            key = child.tag.split('}')[-1]
            result[key] = child.text
        return result
    except Exception:
        return None


def _resolve_subscription_days(amount_value: Decimal) -> int:
    prices = Prices.objects.get(pk=1)
    amount_int = int(amount_value)
    if amount_int == prices.price_1:
        return 31
    if amount_int == prices.price_2:
        return 93
    if amount_int == prices.price_3:
        return 184
    if amount_int == prices.price_4:
        return 366
    if amount_int == prices.price_5:
        return 3
    return 0


def _apply_robokassa_success(transaction: Transaction, amount_value: Decimal, source_label: str,
                             merchant_login: str, password_2: str):
    if transaction.status == 'succeeded':
        return

    telegram_user = transaction.user
    if not telegram_user:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            datetime=datetime.now(),
        )
        return

    transaction.status = 'succeeded'
    transaction.paid = True
    transaction.amount = amount_value
    transaction.currency = transaction.currency or 'RUB'

    payment_info = _fetch_robokassa_payment_info(
        inv_id=str(transaction.robokassa_invoice_id or transaction.id),
        merchant_login=merchant_login,
        password_2=password_2,
    )
    robox_id = (payment_info or {}).get("RoboxID") or (payment_info or {}).get("PaymentID") or \
               (payment_info or {}).get("TransactionID") or (payment_info or {}).get("ID")
    if robox_id:
        transaction.payment_id = str(robox_id)
    elif not transaction.payment_id:
        transaction.payment_id = f"ROBOX_INV_{transaction.robokassa_invoice_id or transaction.id}"

    transaction.robokassa_invoice_id = transaction.robokassa_invoice_id or str(transaction.id)
    transaction.save()

    days = _resolve_subscription_days(amount_value)
    if telegram_user.subscription_status:
        telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(days=days)
        telegram_user.permission_revoked = False
    else:
        telegram_user.subscription_status = True
        telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
        telegram_user.permission_revoked = False

    if transaction.robokassa_is_recurring_parent and not (telegram_user.robokassa_recurring_parent_inv_id or '').strip():
        telegram_user.robokassa_recurring_parent_inv_id = str(transaction.robokassa_invoice_id or transaction.id)
    telegram_user.save()

    referral_percentages = {
        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
    }
    referred_list = TelegramReferral.objects.filter(referred=telegram_user).select_related('referrer')
    if referred_list:
        user_ids_to_pay = [r.referrer.user_id for r in referred_list]
        users_to_pay = {
            u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)
        }
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
                user_to_pay.income = Decimal(user_to_pay.income) + (Decimal(amount_value) * Decimal(percent) / 100)
                user_to_pay.save()
                ReferralTransaction.objects.create(
                    referral=r,
                    amount=Decimal(amount_value) * Decimal(percent) / 100,
                    transaction=transaction,
                )

    Logging.objects.create(
        category="payment",
        log_level="SUCCESS",
        message=f'[{source_label}] [pending-check] Оплата подтверждена InvId={transaction.robokassa_invoice_id or transaction.id}',
        datetime=datetime.now(),
        user=telegram_user,
    )



@shared_task(bind=True, name="robokassa_check_pending_bot")
def robokassa_check_pending_bot(self):
    merchant_login = getattr(settings, "ROBOKASSA_MERCHANT_LOGIN_BOT", None)
    password_2 = getattr(settings, "ROBOKASSA_PASSWORD_2_BOT", None)
    if not merchant_login or not password_2:
        Logging.objects.create(
            category="payment",
            log_level="DANGER",
            datetime=datetime.now(),
        )
        return

    pending_qs = Transaction.objects.filter(
        status="pending",
        paid=False,
        payment_system='RoboKassaBot',
        timestamp__gte=datetime.now() - timedelta(days=3),
    ).select_related('user')

    for transaction in pending_qs:
        try:
            inv_id = str(transaction.robokassa_invoice_id or transaction.id)
            payment_info = _fetch_robokassa_payment_info(inv_id, merchant_login, password_2)
            if not payment_info:
                continue
            state = str(payment_info.get('State') or '').strip()
            if state == '5':
                _apply_robokassa_success(
                    transaction=transaction,
                    amount_value=transaction.amount,
                    source_label='BOT/ROBO',
                    merchant_login=merchant_login,
                    password_2=password_2,
                )
            elif state in {'3', '10'}:
                transaction.status = 'canceled'
                transaction.paid = False
                transaction.save(update_fields=['status', 'paid'])
                Logging.objects.create(
                    category="payment",
                    log_level="WARNING",
                    datetime=datetime.now(),
                    user=transaction.user,
                )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                datetime=datetime.now(),
                user=transaction.user if getattr(transaction, "user", None) else None,
            )


@shared_task(bind=True, name="robokassa_check_pending_site")
def robokassa_check_pending_site(self):
    merchant_login = getattr(settings, "ROBOKASSA_MERCHANT_LOGIN_SITE", None)
    password_2 = getattr(settings, "ROBOKASSA_PASSWORD_2_SITE", None)
    if not merchant_login or not password_2:
        Logging.objects.create(
            category="payment",
            log_level="DANGER",
            datetime=datetime.now(),
        )
        return

    pending_qs = Transaction.objects.filter(
        status="pending",
        paid=False,
        payment_system='RoboKassaSite',
        timestamp__gte=datetime.now() - timedelta(days=3),
    ).select_related('user')

    for transaction in pending_qs:
        try:
            inv_id = str(transaction.robokassa_invoice_id or transaction.id)
            payment_info = _fetch_robokassa_payment_info(inv_id, merchant_login, password_2)
            if not payment_info:
                continue
            state = str(payment_info.get('State') or '').strip()
            if state == '5':
                _apply_robokassa_success(
                    transaction=transaction,
                    amount_value=transaction.amount,
                    source_label='SITE/ROBO',
                    merchant_login=merchant_login,
                    password_2=password_2,
                )
            elif state in {'3', '10'}:
                transaction.status = 'canceled'
                transaction.paid = False
                transaction.save(update_fields=['status', 'paid'])
                Logging.objects.create(
                    category="payment",
                    log_level="WARNING",
                    datetime=datetime.now(),
                    user=transaction.user,
                )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                datetime=datetime.now(),
                user=transaction.user if getattr(transaction, "user", None) else None,
            )


@shared_task
def robokassa_bot_attempt_recurring_payment():
    """
    Рекуррент RoboKassa для бота: POST /Merchant/Recurring.
    Факт оплаты и продление подписки — в RobokassaBotResultView (ResultURL).
    Зарегистрировать задачу в django-celery-beat (интервал как у ukassa_bot_attempt_recurring_payment).
    """
    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f'[CELERY] [BOT] [RoboKassa рекуррент]',
        datetime=datetime.now(),
    )

    users_to_charge = TelegramUser.objects.filter(
        subscription_status=False,
        permission_revoked=False,
    ).exclude(robokassa_recurring_parent_inv_id='')

    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f'[CELERY] [BOT] [RoboKassa рекуррент] [Начало] [пользователей: {users_to_charge.count()}]',
        datetime=datetime.now(),
    )
    success_init = 0
    failed = 0

    merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_BOT
    password_1 = settings.ROBOKASSA_PASSWORD_1_BOT
    is_test = getattr(settings, 'ROBOKASSA_BOT_IS_TEST', False)
    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)

    for user in users_to_charge:
        parent_inv = (user.robokassa_recurring_parent_inv_id or '').strip()
        if not parent_inv:
            continue
        try:
            tx = Transaction.objects.create(
                user=user,
                amount=amount_to_charge,
                currency='RUB',
                side='Приход средств',
                status='pending',
                paid=False,
                income_info=IncomeInfo.objects.get(pk=1),
                description='Рекуррентный платёж (RoboKassa BOT)',
                payment_system='RoboKassaBot',
                robokassa_is_recurring_parent=False,
                robokassa_recurring_previous_inv_id=parent_inv,
            )
            tx.robokassa_invoice_id = str(tx.id)
            tx.save(update_fields=['robokassa_invoice_id'])

            ok, body = post_robokassa_bot_recurring_invoice(
                merchant_login=merchant_login,
                password_1=password_1,
                invoice_id=tx.id,
                previous_invoice_id=parent_inv,
                out_sum=amount_to_charge,
                description=f'Подписка DomVPN рекуррент user={user.user_id}',
                is_test=is_test,
            )
            if ok:
                success_init += 1
                Logging.objects.create(
                    category="payment",
                    log_level="INFO",
                    message=f'Платежный запрос на автосписание Робокасса Бот отправлен успешно',
                    datetime=datetime.now(),
                    user=user
                )
            else:
                failed += 1
                tx.status = 'failed'
                tx.save(update_fields=['status'])
                Logging.objects.create(
                    category="payment",
                    log_level="WARNING",
                    message=f'Списание {body}',
                    datetime=datetime.now(),
                    user=user,
                )
        except Exception as e:
            failed += 1
            Logging.objects.create(
                category="payment",
                log_level="FATAL",
                message=f'{e}',
                datetime=datetime.now(),
                user=user,
            )

    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f'[CELERY] [BOT] [RoboKassa рекуррент] [Конец] инициировано: {success_init}, ошибок: {failed}',
        datetime=datetime.now(),
    )


@shared_task
def robokassa_site_attempt_recurring_payment():
    """
    Рекуррент RoboKassa для сайта: POST /Merchant/Recurring.
    Факт оплаты и продление подписки — в RobokassaSiteResultView (ResultURL).
    """
    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message='[CELERY] [SITE] [RoboKassa рекуррент]',
        datetime=datetime.now(),
    )

    users_to_charge = TelegramUser.objects.filter(
        subscription_status=False,
        permission_revoked=False,
    ).exclude(robokassa_recurring_parent_inv_id='')


    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f'[CELERY] [SITE] [RoboKassa рекуррент] [Начало] [пользователей: {users_to_charge.count()}]',
        datetime=datetime.now(),
    )
    success_init = 0
    skipped = 0
    failed = 0

    merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_SITE
    password_1 = settings.ROBOKASSA_PASSWORD_1_SITE
    is_test = getattr(settings, 'ROBOKASSA_SITE_IS_TEST', False)

    amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
    for user in users_to_charge:
        parent_inv = (user.robokassa_recurring_parent_inv_id or '').strip()
        if not parent_inv:
            skipped += 1
            continue

        # Для сайта берем только цепочки, где parent счёт был оплачен через RoboKassaSite.
        parent_tx = Transaction.objects.filter(
            user=user,
            robokassa_invoice_id=parent_inv,
            payment_system='RoboKassaSite',
            status='succeeded',
            paid=True,
        ).first()
        if not parent_tx:
            skipped += 1
            continue

        try:
            tx = Transaction.objects.create(
                user=user,
                amount=amount_to_charge,
                currency='RUB',
                side='Приход средств',
                status='pending',
                paid=False,
                income_info=IncomeInfo.objects.get(pk=1),
                description='Рекуррентный платёж (RoboKassa SITE)',
                payment_system='RoboKassaSite',
                robokassa_is_recurring_parent=False,
                robokassa_recurring_previous_inv_id=parent_inv,
            )
            tx.robokassa_invoice_id = str(tx.id)
            tx.save(update_fields=['robokassa_invoice_id'])

            ok, body = post_robokassa_bot_recurring_invoice(
                merchant_login=merchant_login,
                password_1=password_1,
                invoice_id=tx.id,
                previous_invoice_id=parent_inv,
                out_sum=amount_to_charge,
                description=f'Подписка DomVPN рекуррент SITE user={user.user_id}',
                is_test=is_test,
            )
            if ok:
                success_init += 1
                Logging.objects.create(
                    category="payment",
                    log_level="INFO",
                    message=f'Платежный запрос на автосписание Робокасса Бот отправлен успешно',
                    datetime=datetime.now(),
                    user=user,
                )
            else:
                failed += 1
                tx.status = 'failed'
                tx.save(update_fields=['status'])
                Logging.objects.create(
                    category="payment",
                    log_level="WARNING",
                    message=f'Списание {body}',
                    datetime=datetime.now(),
                    user=user,
                )
        except Exception as e:
            failed += 1
            Logging.objects.create(
                category="payment",
                log_level="FATAL",
                message=f'{e}',
                datetime=datetime.now(),
                user=user,
            )

    Logging.objects.create(
        category="payment",
        log_level="INFO",
        message=f'[CELERY] [SITE] [RoboKassa рекуррент] [Конец] инициировано: {success_init}, пропущено: {skipped}, ошибок: {failed}',
        datetime=datetime.now(),
    )