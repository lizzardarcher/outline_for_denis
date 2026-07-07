import json
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from urllib.parse import urlencode, quote
import xml.etree.ElementTree as ET


import requests
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction as db_transaction
from django.urls import reverse
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse

from apps.payment.robokassa_subscription import (
    extend_telegram_user_subscription,
    repair_subscription_from_transaction,
    resolve_subscription_days,
    set_robokassa_recurring_parent_if_needed,
)
from bot.models import TelegramUser, Transaction, IncomeInfo, Logging, Prices, TelegramReferral, ReferralSettings, \
    ReferralTransaction


def robokassa_md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest().upper()



def get_robokassa_payment_info(inv_id: str, merchant_login: str, password_2: str):
    """
    Получает информацию о платеже через API RoboKassa.
    Возвращает словарь с данными, включая ID Robox (если доступен).
    """
    url = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpState"

    signature = robokassa_md5(f"{merchant_login}:{inv_id}:{password_2}")

    params = {
        "MerchantLogin": merchant_login,
        "InvoiceID": inv_id,
        "Signature": signature,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()

        # RoboKassa возвращает XML
        root = ET.fromstring(resp.text)

        result = {}
        for child in root:
            result[child.tag] = child.text

        # Проверяем статус
        if result.get("State") == "5":  # 5 = оплачен
            # ID Robox может быть в разных полях, зависит от версии API
            # Обычно это поле "PaymentID" или "TransactionID"
            robox_id = result.get("PaymentID") or result.get("TransactionID") or result.get("ID")
            if robox_id:
                result["RoboxID"] = robox_id

        return result

    except Exception as e:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=f"[ROBO-BOT] [API] Ошибка получения информации о платеже InvId={inv_id}: {e}",
            datetime=datetime.now(),
        )
        return None


def _apply_robokassa_referrals(telegram_user, transaction, amount_value: Decimal) -> None:
    referral_percentages = {
        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
    }

    referred_list = TelegramReferral.objects.filter(referred=telegram_user).select_related('referrer')
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
            income = Decimal(user_to_pay.income) + (Decimal(amount_value) * Decimal(percent) / 100)
            user_to_pay.income = income
            user_to_pay.save()
            ReferralTransaction.objects.create(
                referral=r,
                amount=Decimal(amount_value) * Decimal(percent) / 100,
                transaction=transaction,
            )


def _complete_robokassa_result_payment(
    *,
    transaction: Transaction,
    telegram_user: TelegramUser,
    inv_id,
    amount_value: Decimal,
    merchant_login: str,
    password_2: str,
    payment_system: str,
    log_prefix: str,
) -> None:
    """Подписка и рефералы — до пометки транзакции succeeded (атомарно)."""
    payment_info = get_robokassa_payment_info(
        inv_id=str(inv_id),
        merchant_login=merchant_login,
        password_2=password_2,
    )
    if payment_info and payment_info.get("RoboxID"):
        payment_id = str(payment_info["RoboxID"])
        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"{log_prefix} [ID Robox получен через API] {payment_id} для InvId={inv_id}",
            datetime=datetime.now(),
        )
    else:
        payment_id = f"ROBOX_INV_{inv_id}"
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=f"{log_prefix} [ID Robox не получен через API, используем InvId] {inv_id}",
            datetime=datetime.now(),
        )

    days = resolve_subscription_days(amount_value)

    with db_transaction.atomic():
        extend_telegram_user_subscription(telegram_user, days)
        set_robokassa_recurring_parent_if_needed(telegram_user, transaction, inv_id)
        telegram_user.save()

        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"{log_prefix} [Обработка платежа] [Сумма: {amount_value}] [Дни: {days}]",
            datetime=datetime.now(),
            user=telegram_user,
        )

        _apply_robokassa_referrals(telegram_user, transaction, amount_value)

        transaction.status = 'succeeded'
        transaction.paid = True
        transaction.amount = amount_value
        transaction.currency = transaction.currency or 'RUB'
        transaction.payment_id = payment_id
        transaction.payment_system = transaction.payment_system or payment_system
        transaction.robokassa_invoice_id = transaction.robokassa_invoice_id or str(inv_id)
        transaction.save()

    Logging.objects.create(
        category="payment",
        log_level="SUCCESS",
        message=f"{log_prefix} [Платёж на сумму {amount_value} р. прошёл] [InvId={inv_id}]",
        datetime=datetime.now(),
        user=telegram_user,
    )


class CreateRobokassaPaymentView(LoginRequiredMixin, View):
    """
    Создание платежа в RoboKassa по выбранной подписке.
    Логика похожа на CreatePaymentView для YooKassa, но:
      - сначала создаём Transaction
      - передаём её id как InvId в RoboKassa
      - формируем ссылку и редиректим пользователя.
    """

    def post(self, request, *args, **kwargs):
        try:
            subscription = request.POST.get('subscription')

            prices = Prices.objects.get(pk=1)
            amount = 0
            days = 0

            if float(subscription) == float(prices.price_1):
                amount = float(prices.price_1)
                days = 31
            elif float(subscription) == float(prices.price_2):
                amount = float(prices.price_2)
                days = 93
            elif float(subscription) == float(prices.price_3):
                amount = float(prices.price_3)
                days = 184
            elif float(subscription) == float(prices.price_4):
                amount = float(prices.price_4)
                days = 366
            elif float(subscription) == float(prices.price_5):
                amount = float(prices.price_5)
                days = 3

            amount_decimal = Decimal(str(amount))

            # Пользователь из связанного Telegram-профиля
            telegram_user = request.user.profile.telegram_user

            # 1) Создаём pending-транзакцию
            transaction = Transaction.objects.create(
                status='pending',
                paid=False,
                amount=amount_decimal,
                user=telegram_user,
                currency='RUB',
                income_info=IncomeInfo.objects.get(pk=1),
                side='Приход средств',
                description=f'Приобретение подписки (RoboKassa Site, {days} дн.)',
                payment_system='RoboKassaSite',
                robokassa_is_recurring_parent=True,
            )

            transaction.robokassa_invoice_id = str(transaction.id)
            transaction.robokassa_recurring_previous_inv_id = str(transaction.id)
            transaction.save()
            # transaction.save(update_fields=['robokassa_invoice_id'])
            inv_id = transaction.id  # будем использовать как InvId в RoboKassa

            # 2) Формируем ссылку RoboKassa
            # Формируем Receipt
            receipt = {
                "sno": "usn_income",  # или "osn", зависит от вашей СНО
                "items": [
                    {
                        "name": f"Подписка DomVPN на {days} дн.",
                        "quantity": 1,
                        "sum": int(amount_decimal),  # в копейках
                        "payment_method": "full_payment",
                        "payment_object": "service",
                        "tax": "vat0"
                    }
                ]
            }

            # URL-кодируем Receipt перед включением в подпись
            receipt_url_encoded = quote(json.dumps(receipt, separators=(',', ':')), safe='')

            merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_SITE
            password_1 = settings.ROBOKASSA_PASSWORD_1_SITE
            base_url = getattr(
                settings,
                'ROBOKASSA_ENDPOINT',
                'https://auth.robokassa.ru/Merchant/Index.aspx',
            )
            is_test = getattr(settings, 'ROBOKASSA_IS_TEST', False)

            out_sum_str = f"{amount_decimal:.2f}"

            # signature = robokassa_md5(
            #     f"{merchant_login}:{out_sum_str}:{inv_id}:{password_1}"
            # )

            # Подпись теперь включает Receipt
            signature = robokassa_md5(
                f"{merchant_login}:{out_sum_str}:{inv_id}:{receipt_url_encoded}:{password_1}"
            )

            success_url = request.build_absolute_uri(
                reverse('robokassa_success')
            )
            fail_url = request.build_absolute_uri(
                reverse('robokassa_fail')
            )

            # params = {
            #     'MerchantLogin': merchant_login,
            #     'OutSum': out_sum_str,
            #     'InvId': str(inv_id),
            #     'Description': f'Подписка DomVPN на {days} дн.',
            #     'SignatureValue': signature,
            #     'SuccessURL': success_url,
            #     'FailURL': fail_url,
            #     'Recurring': 'true',
            # }

            params = {
                'MerchantLogin': merchant_login,
                'OutSum': out_sum_str,
                'InvId': str(inv_id),
                'Description': f'Подписка DomVPN на {days} дн.',
                'SignatureValue': signature,
                'SuccessURL': success_url,
                'FailURL': fail_url,
                'Recurring': 'true',
                'Receipt': receipt_url_encoded,
            }

            redirect_url = f"{base_url}?{urlencode(params)}"

            Logging.objects.create(
                category="payment",
                log_level="INFO",
                message=f'[WEB] [ROBO] [Платёжный запрос на сумму {out_sum_str} р.]',
                datetime=datetime.now(),
                user=telegram_user,
            )
            return redirect(redirect_url)

        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f'[WEB] [ROBO] [Ошибка платёжного запроса {str(traceback.format_exc())}]',
                datetime=datetime.now(),
                user=request.user.profile.telegram_user if hasattr(request.user, "profile") else None,
            )
            return redirect('profile')


@method_decorator(csrf_exempt, name='dispatch')
class RobokassaSiteResultView(View):
    """
    ResultURL для RoboKassa.
    Здесь проверяем подпись, помечаем Transaction как succeeded
    и продлеваем подписку / считаем реферальные начисления.
    """

    def post(self, request, *args, **kwargs):
        # Логируем входящие параметры для отладки
        all_params = dict(request.POST.items()) if hasattr(request.POST, 'items') else {}
        all_get_params = dict(request.GET.items()) if hasattr(request.GET, 'items') else {}
        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"[ROBO-SITE] [Webhook] Все POST параметры: {all_params}, Все GET параметры: {all_get_params}",
            datetime=datetime.now(),
        )
        out_sum = request.POST.get('OutSum') or request.GET.get('OutSum')
        inv_id = request.POST.get('InvId') or request.GET.get('InvId')
        signature = (request.POST.get('SignatureValue') or request.GET.get('SignatureValue') or '').upper()

        if not out_sum or not inv_id or not signature:
            return HttpResponse('Bad request', status=400)

        # Подпись для ResultURL: MD5(OutSum:InvId:Password2Site)
        expected = robokassa_md5(f"{out_sum}:{inv_id}:{settings.ROBOKASSA_PASSWORD_2_SITE}")
        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"[ROBO-SITE] [Webhook] OutSum={out_sum}, InvId={inv_id}, Signature={signature}, Expected={expected}",
            datetime=datetime.now(),
        )
        if signature != expected:
            return HttpResponse('bad sign', status=403)

        try:
            inv_id_int = int(inv_id)
        except ValueError:
            return HttpResponse('Bad InvId', status=400)

        transaction = Transaction.objects.select_related('user').filter(id=inv_id_int).first()
        if not transaction:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"[ROBO-SITE] [Result] Транзакция с id={inv_id_int} не найдена",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        if transaction.status == 'succeeded':
            repair_subscription_from_transaction(transaction)
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        telegram_user = transaction.user
        if not telegram_user:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"[ROBO-SITE] [Result] У транзакции id={inv_id_int} нет привязанного TelegramUser",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        try:
            amount_value = Decimal(out_sum)
        except Exception:
            amount_value = transaction.amount

        try:
            _complete_robokassa_result_payment(
                transaction=transaction,
                telegram_user=telegram_user,
                inv_id=inv_id,
                amount_value=amount_value,
                merchant_login=settings.ROBOKASSA_MERCHANT_LOGIN_SITE,
                password_2=settings.ROBOKASSA_PASSWORD_2_SITE,
                payment_system='RoboKassaSite',
                log_prefix='[ROBO-SITE]',
            )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"[ROBO-SITE] [Ошибка при обработке ResultURL]\n{traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )
        return HttpResponse(f"OK{inv_id}", content_type='text/plain')


@method_decorator(csrf_exempt, name='dispatch')
class RobokassaBotResultView(View):
    """
    ResultURL для магазина Robokassa, используемого Telegram-ботом.
    Здесь:
      - проверяем подпись (Password2 бота),
      - помечаем Transaction как succeeded,
      - продлеваем подписку TelegramUser,
      - считаем реферальные начисления.
    """

    def post(self, request, *args, **kwargs):

        # Логируем ВСЕ параметры для отладки
        all_params = dict(request.POST.items()) if hasattr(request.POST, 'items') else {}
        all_get_params = dict(request.GET.items()) if hasattr(request.GET, 'items') else {}

        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"[ROBO-BOT] [Webhook] Все POST параметры: {all_params}, Все GET параметры: {all_get_params}",
            datetime=datetime.now(),
        )
        out_sum = request.POST.get('OutSum') or request.GET.get('OutSum')
        inv_id = request.POST.get('InvId') or request.GET.get('InvId')
        signature = (request.POST.get('SignatureValue') or request.GET.get('SignatureValue') or '').upper()

        # Возможные параметры с ID Robox (проверь документацию RoboKassa):
        robox_id = request.POST.get('PaymentID') or request.GET.get('PaymentID') or \
                   request.POST.get('MerchantOrderId') or request.GET.get('MerchantOrderId') or \
                   request.POST.get('RoboxID') or request.GET.get('RoboxID') or \
                   request.POST.get('TransactionID') or request.GET.get('TransactionID')

        if not out_sum or not inv_id or not signature:
            return HttpResponse('Bad request', status=400)

        # Подпись для ResultURL бота: MD5(OutSum:InvId:Password2Bot)
        expected = robokassa_md5(f"{out_sum}:{inv_id}:{settings.ROBOKASSA_PASSWORD_2_BOT}")

        Logging.objects.create(
            category="payment",
            log_level="INFO",
            message=f"[ROBO-BOT] [Webhook] OutSum={out_sum}, InvId={inv_id}, Signature={signature}, Expected={expected}",
            datetime=datetime.now(),
        )
        if signature != expected:
            return HttpResponse('bad sign', status=403)

        try:
            inv_id_int = int(inv_id)
        except ValueError:
            return HttpResponse('Bad InvId', status=400)

        # Предполагаем, что для бота тоже используешь InvId = Transaction.id
        transaction = Transaction.objects.select_related('user').filter(id=inv_id_int).first()

        if not transaction:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"[ROBO-BOT] [Result] Транзакция с id={inv_id_int} не найдена",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        # Если уже обработано ранее — подтверждаем и при необходимости восстанавливаем подписку
        if transaction.status == 'succeeded':
            repair_subscription_from_transaction(transaction)
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        telegram_user = transaction.user  # ForeignKey на TelegramUser
        if not telegram_user:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"[ROBO-BOT] [Result] У транзакции id={inv_id_int} нет привязанного TelegramUser",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        try:
            amount_value = Decimal(out_sum)
        except Exception:
            amount_value = transaction.amount  # fallback

        try:
            _complete_robokassa_result_payment(
                transaction=transaction,
                telegram_user=telegram_user,
                inv_id=inv_id,
                amount_value=amount_value,
                merchant_login=settings.ROBOKASSA_MERCHANT_LOGIN_BOT,
                password_2=settings.ROBOKASSA_PASSWORD_2_BOT,
                payment_system='RoboKassaBot',
                log_prefix='[ROBO-BOT]',
            )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"[ROBO-BOT] [Ошибка при обработке ResultURL]\n{traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )
        # Обязательный ответ RoboKassa
        return HttpResponse(f"OK{inv_id}", content_type='text/plain')


class RobokassaSuccessView(TemplateView):
    """
    SuccessURL (браузер пользователя после успешного платежа).
    Вся “настоящая” логика уже в ResultURL, здесь только красивая страница.
    """
    template_name = 'payments/payment_success.html'


class RobokassaFailView(TemplateView):
    """
    FailURL (браузер пользователя после неуспешного/отменённого платежа).
    """
    template_name = 'payments/payment_failure.html'
