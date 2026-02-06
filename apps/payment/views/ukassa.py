import traceback
from datetime import datetime, timedelta
from decimal import Decimal
import json
import hashlib
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncYear, TruncMonth
from django.urls import reverse
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse

from yookassa import Configuration, Payment

from openpyxl import Workbook

from bot.models import TelegramUser, Transaction, IncomeInfo, Logging, Prices, TelegramReferral, ReferralSettings, \
    ReferralTransaction


def robokassa_md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest().upper()

class CreatePaymentView(View):
    # def post(self, request, *args, **kwargs):
    #     messages.error(request, 'К сожалению, на данный момент мы не можем оказать услуги в связи с проблемами с платёжной системой. Приём оплаты возобновится примерно 15.09.')
    #     return redirect('profile')
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

            # Настройка ЮKassa
            Configuration.account_id = settings.YOOKASSA_SHOP_ID_SITE
            Configuration.secret_key = settings.YOOKASSA_SECRET_SITE
            email = request.user.email if request.user.email else "noemail@noemail.ru"
            payment = Payment.create({
                "amount": {
                    "value": str(amount),
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f'https://domvpn.store/payment/payment-success/?id=&date={datetime.now()}&amount={amount}',
                    "enforce": False
                },
                "capture": True,
                "description": f'Подписка DomVPN на {days} дн.',
                "save_payment_method": True,
                "metadata": {
                    'user_id': request.user.id,
                    'telegram_user_id': request.user.profile.telegram_user.user_id,
                },
                "receipt": {
                    "customer": {
                        "email": email
                        # "phone": request.user.profile.phone_number,
                    },
                    "items": [
                        {
                            "description": f'Подписка DomVPN на {days} дн.',
                            "quantity": "1.00",
                            "amount": {
                                "value": str(amount),
                                "currency": "RUB"
                            },
                            "vat_code": 4,
                            "payment_subject": "service",
                            "payment_mode": "full_payment"
                        }
                    ]
                }
            })

            request.session['yookassa_payment_id'] = payment.id
            request.session['yookassa_payment_amount'] = float(amount)

            Transaction.objects.create(status='pending', paid=False, amount=amount,
                                       user=request.user.profile.telegram_user,
                                       currency='RUB', income_info=IncomeInfo.objects.get(pk=1), side='Приход средств',
                                       description='Приобретение подписки', payment_id=payment.id)
            Logging.objects.create(log_level="INFO", message=f'[WEB] [Платёжный запрос на сумму {str(amount)} р.]',
                                   datetime=datetime.now(), user=self.request.user.profile.telegram_user)

            # Перенаправляем пользователя на страницу ЮKassa
            return redirect(payment.confirmation.confirmation_url)

        except Exception as e:
            Logging.objects.create(log_level="DANGER",
                                   message=f'[WEB] [Ошибка платёжного запроса {str(traceback.format_exc())}]',
                                   datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            return redirect('profile')


class PaymentSuccessView(TemplateView):
    template_name = 'payments/payment_success.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class PaymentFailureView(TemplateView):
    template_name = 'payments/payment_failure.html'


@method_decorator(csrf_exempt, name='dispatch')
class YookassaTGBOTWebhookView(View):
    def post(self, request, *args, **kwargs):

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse('Invalid request body', status=400)

        event_type = data.get('event')
        payment_data = data.get('object')
        metadata = payment_data.get('metadata')
        telegram_user_id = int(metadata.get('telegram_user_id'))
        telegram_user = TelegramUser.objects.get(user_id=telegram_user_id)

        # Обработка события
        if 'succeeded' in str(event_type):
            Logging.objects.create(log_level="SUCCESS", message=f'[BOT] [Приём вебхука] [{event_type}]',
                                   datetime=datetime.now())
            try:
                payment_id = payment_data.get('id')
                status = payment_data.get('status')
                payment_method_id = payment_data.get('payment_method').get('id')
                amount_value = float(payment_data.get('amount').get('value'))
                transaction = Transaction.objects.filter(payment_id=payment_id).first()

                if transaction.status != 'succeeded' and int(amount_value) > 0:
                    transaction.status = status
                    transaction.paid = True
                    transaction.save()

                    days = 0
                    if int(amount_value) == Prices.objects.get(id=1).price_1:
                        days = 31
                    elif int(amount_value) == Prices.objects.get(id=1).price_2:
                        days = 93
                    elif int(amount_value) == Prices.objects.get(id=1).price_3:
                        days = 184
                    elif int(amount_value) == Prices.objects.get(id=1).price_4:
                        days = 366
                    elif int(amount_value) == Prices.objects.get(id=1).price_5:
                        days = 3

                    if telegram_user.subscription_status:
                        telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(
                            days=days)
                        telegram_user.payment_method_id = payment_method_id
                        telegram_user.permission_revoked = False
                        telegram_user.save()
                    else:
                        telegram_user.subscription_status = True
                        telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
                        telegram_user.payment_method_id = payment_method_id
                        telegram_user.permission_revoked = False
                        telegram_user.save()

                    Logging.objects.create(log_level="INFO",
                                           message=f'[BOT] [Обработка платежа] [{event_type}] [Сумма: {amount_value}] [Дни:{days}]',
                                           datetime=datetime.now(), user=telegram_user)


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
                        # Prefetch all the user objects in one call!
                        users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}

                        for r in referred_list:
                            level = r.level
                            user_to_pay = users_to_pay.get(r.referrer.user_id)  # Access pre-fetched user
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
                                user_to_pay.save()  # Save the user to pay not the original user
                                ReferralTransaction.objects.create(
                                    referral=r,
                                    amount=Decimal(amount_value) * Decimal(percent) / 100,
                                    transaction=transaction
                                )
                    Logging.objects.create(log_level="SUCCESS",
                                           message=f'[BOT] [Платёж  на сумму {str(amount_value)} р. прошёл]',
                                           datetime=datetime.now(), user=telegram_user)
                    return HttpResponse(f'Обновляем баланс пользователя', status=200)

            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[BOT]  [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=telegram_user)
                return HttpResponse('OK', status=200)

        elif 'canceled' in str(event_type):
            Logging.objects.create(log_level="WARNING", message=f'[BOT] [Приём вебхука] [{event_type}]',
                                   datetime=datetime.now())
            try:
                payment_id = payment_data.get('id')
                status = payment_data.get('status')
                transaction = Transaction.objects.filter(payment_id=payment_id).first()
                transaction.status = status
                transaction.paid = False
                transaction.save()
                Logging.objects.create(log_level="WARNING",
                                       message=f'[BOT] [Платёж  на сумму {str(traceback.format_exc())} р. отменён]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[BOT] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            return HttpResponse('OK', status=200)
        else:
            Logging.objects.create(log_level="DANGER", message=f'[BOT] [Непонятно что] [.......]',
                                   datetime=datetime.now())
            return HttpResponse('OK', status=200)


@method_decorator(csrf_exempt, name='dispatch')
class YookassaSiteWebhookView(View):
    def post(self, request, *args, **kwargs):
        # Logging.objects.create(log_level="WARNING", message=f'[WEB] [Приём вебхука] [{str(request.body)}]', datetime=datetime.now())

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse('Invalid request body', status=400)

        event_type = data.get('event')
        payment_data = data.get('object')
        metadata = payment_data.get('metadata')
        telegram_user_id = int(metadata.get('telegram_user_id'))
        telegram_user = TelegramUser.objects.get(user_id=telegram_user_id)

        # Обработка события
        if 'succeeded' in str(event_type):
            Logging.objects.create(log_level="SUCCESS", message=f'[WEB] [Приём вебхука] [{event_type}]',
                                   datetime=datetime.now())
            try:
                payment_id = payment_data.get('id')
                status = payment_data.get('status')
                payment_method_id = payment_data.get('payment_method').get('id')
                amount_value = float(payment_data.get('amount').get('value'))
                transaction = Transaction.objects.filter(payment_id=payment_id).first()

                if transaction.status != 'succeeded' and int(amount_value) > 0:
                    transaction.status = status
                    transaction.paid = True
                    transaction.save()

                    days = 0
                    if int(amount_value) == Prices.objects.get(id=1).price_1:
                        days = 31
                    elif int(amount_value) == Prices.objects.get(id=1).price_2:
                        days = 93
                    elif int(amount_value) == Prices.objects.get(id=1).price_3:
                        days = 184
                    elif int(amount_value) == Prices.objects.get(id=1).price_4:
                        days = 366
                    elif int(amount_value) == Prices.objects.get(id=1).price_5:
                        days = 3

                    if telegram_user.subscription_status:
                        telegram_user.subscription_expiration = telegram_user.subscription_expiration + timedelta(
                            days=days)
                        telegram_user.permission_revoked = False
                        telegram_user.payment_method_id = payment_method_id
                        telegram_user.save()
                    else:
                        telegram_user.subscription_status = True
                        telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
                        telegram_user.permission_revoked = False
                        telegram_user.payment_method_id = payment_method_id
                        telegram_user.save()

                    Logging.objects.create(log_level="INFO",
                                           message=f'[BOT] [Обработка платежа] [{event_type}] [Сумма: {amount_value}] [Дни:{days}]',
                                           datetime=datetime.now(), user=telegram_user)

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
                        # Prefetch all the user objects in one call!
                        users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}

                        for r in referred_list:
                            level = r.level
                            user_to_pay = users_to_pay.get(r.referrer.user_id)  # Access pre-fetched user
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
                                        Decimal(amount_value) * Decimal(percent) / 100)
                                user_to_pay.income = income
                                user_to_pay.save()  # Save the user to pay not the original user
                                ReferralTransaction.objects.create(
                                    referral=r,
                                    amount=Decimal(amount_value) * Decimal(percent) / 100,
                                    transaction=transaction
                                )
                    Logging.objects.create(log_level="SUCCESS",
                                           message=f'[WEB] [Платёж  на сумму {str(amount_value)} р. прошёл]',
                                           datetime=datetime.now(), user=telegram_user)
                    return HttpResponse(f'Обновляем баланс пользователя', status=200)

            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[WEB] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=telegram_user)
                return HttpResponse('OK', status=200)

        elif 'canceled' in str(event_type):
            Logging.objects.create(log_level="WARNING", message=f'[WEB] [Приём вебхука] [{event_type}]',
                                   datetime=datetime.now())
            try:
                payment_id = payment_data.get('id')
                status = payment_data.get('status')
                transaction = Transaction.objects.filter(payment_id=payment_id).first()
                transaction.status = status
                transaction.paid = False
                transaction.save()
                Logging.objects.create(log_level="WARNING",
                                       message=f'[WEB] [Платёж  на сумму {str(traceback.format_exc())} р. отменён]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[WEB] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            return HttpResponse('OK', status=200)
        else:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] [Непонятно что] [.......]',
                                   datetime=datetime.now())
            return HttpResponse('OK', status=200)