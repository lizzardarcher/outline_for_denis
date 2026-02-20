import traceback
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse

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
            log_level="WARNING",
            message=f"[ROBO-BOT] [API] Ошибка получения информации о платеже InvId={inv_id}: {e}",
            datetime=datetime.now(),
        )
        return None


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
                description=f'Приобретение подписки (RoboKassa, {days} дн.)',
            )

            inv_id = transaction.id  # будем использовать как InvId в RoboKassa

            # 2) Формируем ссылку RoboKassa
            merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_SITE
            password_1 = settings.ROBOKASSA_PASSWORD_1_SITE
            base_url = getattr(
                settings,
                'ROBOKASSA_ENDPOINT',
                'https://auth.robokassa.ru/Merchant/Index.aspx',
            )
            is_test = getattr(settings, 'ROBOKASSA_IS_TEST', False)

            out_sum_str = f"{amount_decimal:.2f}"

            signature = robokassa_md5(
                f"{merchant_login}:{out_sum_str}:{inv_id}:{password_1}"
            )

            success_url = request.build_absolute_uri(
                reverse('robokassa_success')
            )
            fail_url = request.build_absolute_uri(
                reverse('robokassa_fail')
            )

            params = {
                'MerchantLogin': merchant_login,
                'OutSum': out_sum_str,
                'InvId': str(inv_id),
                'Description': f'Подписка DomVPN на {days} дн.',
                'SignatureValue': signature,
                'SuccessURL': success_url,
                'FailURL': fail_url,
            }
            if is_test:
                params['IsTest'] = '1'

            redirect_url = f"{base_url}?{urlencode(params)}"

            Logging.objects.create(
                log_level="INFO",
                message=f'[WEB] [ROBO] [Платёжный запрос на сумму {out_sum_str} р.]',
                datetime=datetime.now(),
                user=telegram_user,
            )

            return redirect(redirect_url)

        except Exception:
            Logging.objects.create(
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
        out_sum = request.POST.get('OutSum') or request.GET.get('OutSum')
        inv_id = request.POST.get('InvId') or request.GET.get('InvId')
        signature = (request.POST.get('SignatureValue') or request.GET.get('SignatureValue') or '').upper()

        if not out_sum or not inv_id or not signature:
            return HttpResponse('Bad request', status=400)

        # Подпись для ResultURL: MD5(OutSum:InvId:Password2)
        expected = robokassa_md5(f"{out_sum}:{inv_id}:{settings.ROBOKASSA_PASSWORD_2_SITE}")
        if signature != expected:
            return HttpResponse('bad sign', status=403)

        try:
            inv_id_int = int(inv_id)
        except ValueError:
            return HttpResponse('Bad InvId', status=400)

        # Предполагаем, что при создании счёта в RoboKassa вы передаёте InvId = Transaction.id
        transaction = Transaction.objects.select_related('user').filter(id=inv_id_int).first()

        if not transaction:
            # Транзакцию не нашли, но для RoboKassa всё равно нужно вернуть OK, иначе будут ретраи
            Logging.objects.create(
                log_level="WARNING",
                message=f"[ROBO] [Result] Транзакция с id={inv_id_int} не найдена",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        # Если уже обработали ранее — просто возвращаем OK (идемпотентность)
        if transaction.status == 'succeeded':
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        telegram_user = transaction.user  # ForeignKey на TelegramUser
        if not telegram_user:
            Logging.objects.create(
                log_level="WARNING",
                message=f"[ROBO] [Result] У транзакции id={inv_id_int} нет привязанного TelegramUser",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        try:
            amount_value = Decimal(out_sum)
        except Exception:
            amount_value = transaction.amount  # fallback

        try:
            # Обновляем транзакцию
            transaction.status = 'succeeded'
            transaction.paid = True
            transaction.amount = amount_value
            transaction.currency = transaction.currency or 'RUB'
            transaction.save()

            # Определяем срок подписки по сумме (как в YookassaSiteWebhookView)
            prices = Prices.objects.get(pk=1)
            days = 0
            if int(amount_value) == prices.price_1:
                days = 31
            elif int(amount_value) == prices.price_2:
                days = 93
            elif int(amount_value) == prices.price_3:
                days = 184
            elif int(amount_value) == prices.price_4:
                days = 366
            elif int(amount_value) == prices.price_5:
                days = 3

            # Обновляем подписку (без сохранения payment_method_id — RoboKassa не даёт токен)
            if telegram_user.subscription_status:
                telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(days=days)
                telegram_user.permission_revoked = False
                telegram_user.save()
            else:
                telegram_user.subscription_status = True
                telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
                telegram_user.permission_revoked = False
                telegram_user.save()

            Logging.objects.create(
                log_level="INFO",
                message=f"[ROBO] [Обработка платежа] [Сумма: {amount_value}] [Дни: {days}]",
                datetime=datetime.now(),
                user=telegram_user,
            )

            # Реферальные начисления (копия логики из Yookassa*WebhookView)
            referral_percentages = {
                1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                5: ReferralSettings.objects.get(pk=1).level_5_percentage,
            }

            referred_list = TelegramReferral.objects.filter(
                referred=telegram_user
            ).select_related('referrer')

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
                        income = Decimal(user_to_pay.income) + (
                                Decimal(amount_value) * Decimal(percent) / 100
                        )
                        user_to_pay.income = income
                        user_to_pay.save()
                        ReferralTransaction.objects.create(
                            referral=r,
                            amount=Decimal(amount_value) * Decimal(percent) / 100,
                            transaction=transaction,
                        )

            Logging.objects.create(
                log_level="SUCCESS",
                message=f"[ROBO] [Платёж на сумму {amount_value} р. прошёл] [InvId={inv_id}]",
                datetime=datetime.now(),
                user=telegram_user,
            )

        except Exception:
            Logging.objects.create(
                log_level="DANGER",
                message=f"[ROBO] [Ошибка при обработке ResultURL]\n{traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )

        # Обязательный ответ RoboKassa
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
                log_level="WARNING",
                message=f"[ROBO-BOT] [Result] Транзакция с id={inv_id_int} не найдена",
                datetime=datetime.now(),
            )
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        # Если уже обработано ранее — просто подтверждаем (идемпотентность)
        if transaction.status == 'succeeded':
            return HttpResponse(f"OK{inv_id}", content_type='text/plain')

        telegram_user = transaction.user  # ForeignKey на TelegramUser
        if not telegram_user:
            Logging.objects.create(
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
            # Обновляем транзакцию
            transaction.status = 'succeeded'
            transaction.paid = True
            transaction.amount = amount_value
            transaction.currency = transaction.currency or 'RUB'

            # Пытаемся получить ID Robox через API RoboKassa
            payment_info = get_robokassa_payment_info(
                inv_id=str(inv_id),
                merchant_login=settings.ROBOKASSA_MERCHANT_LOGIN_BOT,
                password_2=settings.ROBOKASSA_PASSWORD_2_BOT,
            )

            if payment_info and payment_info.get("RoboxID"):
                transaction.payment_id = str(payment_info["RoboxID"])
                Logging.objects.create(
                    log_level="INFO",
                    message=f"[ROBO-BOT] [ID Robox получен через API] {payment_info['RoboxID']} для InvId={inv_id}",
                    datetime=datetime.now(),
                )
            else:
                # Fallback: сохраняем InvId (хотя это не ID Robox, но для связи транзакций сойдёт)
                transaction.payment_id = f"ROBOX_INV_{inv_id}"  # Префикс для понимания, что это не настоящий ID Robox
                Logging.objects.create(
                    log_level="WARNING",
                    message=f"[ROBO-BOT] [ID Robox не получен через API, используем InvId] {inv_id}",
                    datetime=datetime.now(),
                )

            transaction.save()

            # Определяем срок подписки по сумме (как в YookassaTGBOTWebhookView)
            prices = Prices.objects.get(pk=1)
            days = 0
            if int(amount_value) == prices.price_1:
                days = 31
            elif int(amount_value) == prices.price_2:
                days = 93
            elif int(amount_value) == prices.price_3:
                days = 184
            elif int(amount_value) == prices.price_4:
                days = 366
            elif int(amount_value) == prices.price_5:
                days = 3

            # Обновляем подписку (без payment_method_id — RoboKassa токен не даёт)
            if telegram_user.subscription_status:
                telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(days=days)
                telegram_user.permission_revoked = False
                telegram_user.save()
            else:
                telegram_user.subscription_status = True
                telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
                telegram_user.permission_revoked = False
                telegram_user.save()

            Logging.objects.create(
                log_level="INFO",
                message=f"[ROBO-BOT] [Обработка платежа] [Сумма: {amount_value}] [Дни: {days}]",
                datetime=datetime.now(),
                user=telegram_user,
            )

            # Реферальные начисления (копия логики из бот-вебхука YooKassa)
            referral_percentages = {
                1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                5: ReferralSettings.objects.get(pk=1).level_5_percentage,
            }

            referred_list = TelegramReferral.objects.filter(
                referred=telegram_user
            ).select_related('referrer')

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
                        income = Decimal(user_to_pay.income) + (
                                Decimal(amount_value) * Decimal(percent) / 100
                        )
                        user_to_pay.income = income
                        user_to_pay.save()
                        ReferralTransaction.objects.create(
                            referral=r,
                            amount=Decimal(amount_value) * Decimal(percent) / 100,
                            transaction=transaction,
                        )

            Logging.objects.create(
                log_level="SUCCESS",
                message=f"[ROBO-BOT] [Платёж на сумму {amount_value} р. прошёл] [InvId={inv_id}]",
                datetime=datetime.now(),
                user=telegram_user,
            )

        except Exception:
            Logging.objects.create(
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
