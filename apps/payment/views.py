# your_app/views.py
import traceback
from datetime import datetime, timedelta

from django.contrib import messages
from django.urls import reverse
from django.views.generic import TemplateView

from django.shortcuts import redirect, render
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from yookassa import Configuration, Payment
import hashlib, hmac, json
from django.http import HttpResponse
from bot.models import TelegramUser, Transaction, IncomeInfo, Logging, Prices, TelegramReferral, ReferralSettings


class CreatePaymentView(View):
    def post(self, request, *args, **kwargs):

        amount = request.POST.get('amount')
        try:
            amount = float(amount)
        except ValueError:
            messages.error(request, 'Укажите сумму в поле для пополнения баланса.')
            return redirect(reverse('profile'))

        # Настройка ЮKassa
        Configuration.account_id = int(settings.YOOKASSA_SHOP_ID)
        Configuration.secret_key = settings.YOOKASSA_SECRET

        payment = Payment.create({
            "amount": {
                "value": amount,
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f'https://domvpn.store/payment/payment-success/?id=&date={datetime.now()}&amount={amount}',
                "enforce": False
            },
            "capture": True,  # Автоматическое списание средств
            "description": settings.YOOKASSA_PAYMENT_DESCRIPTION,
            "metadata": {
                'user_id': request.user.id,
                'telegram_user_id': request.user.profile.telegram_user.id,
            }
        }, )

        # Сохраняем payment_id в сессию (потом понадобится)
        request.session['yookassa_payment_id'] = payment.id
        # Сохраняем сумму в сессию, чтобы потом понять, на какую сумму пользователь пополнил баланс
        request.session['yookassa_payment_amount'] = float(amount)
        # Перенаправляем пользователя на страницу ЮKassa

        Transaction.objects.create(status='pending', paid=False, amount=amount, user=request.user.profile.telegram_user,
                                   currency='RUB', income_info=IncomeInfo.objects.get(pk=1), side='Приход средств',
                                   description='Пополнение баланса пользователя', payment_id=payment.id)
        Logging.objects.create(log_level="INFO", message=f'[WEB] [Платёжный запрос на сумму {str(amount)} р.]',
                               datetime=datetime.now(), user=self.request.user.profile.telegram_user)
        return redirect(payment.confirmation.confirmation_url)


class PaymentSuccessView(TemplateView):
    template_name = 'payments/payment_success.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class PaymentFailureView(TemplateView):
    template_name = 'payments/payment_failure.html'


@method_decorator(csrf_exempt, name='dispatch')
class YookassaWebhookView(View):
    def post(self, request, *args, **kwargs):
        """
        {'type': 'notification',
         'event': 'payment.succeeded',
          'object':
                {'id': '2f24d421d-000f-5000-9000-1ab1512d5d710a',
                 'status': 'succeeded',
                  'amount':
                        {'value': '51.00',
                         'currency': 'RUB'},
                         'income_amount':
                            {'value': '49.21',
                             'currency': 'RUB'},
                             'description': 'Ð\x9fÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ Ð±Ð°Ð»Ð°Ð½Ñ\x81Ð° Ð¿Ð¾Ð»Ñ\x8cÐ·Ð¾Ð²Ð°Ñ\x82ÐµÐ»Ñ\x8f',
                             'recipient': {'account_id': '10222620', 'gateway_id': '23955185'},
                              'payment_method': {'type': 'yoo_money', 'id': '2f2d421d-000f-5000-9000-1ab151d5d70a',
                              'saved': False, 'status': 'inactive', 'title': 'YooMoney wallet 410011758831136', 'account_number': '410011758831136'},
                              'captured_at': '2025-01-30T07:46:41.994Z', 'created_at': '2025-01-30T07:46:37.008Z', 'test': True, 'refunded_amount':
                              {'value': '0.00', 'currency': 'RUB'}, 'paid': True, 'refundable': True,
                               'metadata': {'user_id': '1556761461968', 'cms_name': 'yookassa_sdk_python', 'telegram_user_id': '52324'}}}

        """

        # Получаем данные из запроса
        body = request.body

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return HttpResponse('Invalid request body', status=400)

        event_type = data.get('event')

        # Обработка события
        if event_type == 'payment.succeeded':
            self.handle_successful_payment(data.get('object'))
            return HttpResponse('OK', status=200)
        elif event_type == 'payment.canceled':
            self.handle_canceled_payment(data.get('object'))
            return HttpResponse('OK', status=200)
        else:
            # logger.info(f"Unhandled event type: {event_type}")
            return HttpResponse('OK', status=200)

    def check_signature(self, body, signature):
        """ Проверка подписи Yookassa """
        secret = settings.YOOKASSA_SECRET
        string_to_sign = body
        key = secret.encode('utf-8')
        message = string_to_sign.encode('utf-8')
        calculated_signature = hmac.new(key, message, hashlib.sha256).hexdigest()
        if calculated_signature == signature:
            return True
        return False

    def handle_successful_payment(self, payment_data):
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        metadata = payment_data.get('metadata')
        amount_value = float(payment_data.get('amount').get('value'))
        telegram_user_id = int(metadata.get('telegram_user_id'))
        telegram_user = TelegramUser.objects.get(id=telegram_user_id)
        user_balance = float(telegram_user.balance) + float(amount_value)

        try:

            transaction = Transaction.objects.filter(payment_id=payment_id).first()
            if transaction.status != 'succeeded' and int(amount_value) > 0:
                transaction.status = status
                transaction.paid = True
                transaction.save()

                telegram_user.balance = user_balance
                telegram_user.save()

                income = IncomeInfo.objects.get(id=1)
                income.total_amount = float(income.total_amount) + float(amount_value)
                income.save()

                Logging.objects.create(log_level="SUCCESS",
                                       message=f'[WEB] [Платёж  на сумму {str(amount_value)} р. прошёл]',
                                       datetime=datetime.now(), user=telegram_user)
                return HttpResponse(f'Обновляем баланс пользователя', status=200)
        except Exception as e:
            Logging.objects.create(log_level="DANGER",
                                   message=f'[WEB] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                   datetime=datetime.now(), user=telegram_user)

    def handle_canceled_payment(self, payment_data):
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


#########################################################################
#########################################################################

class TestCreatePaymentView(View):
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
            Configuration.account_id = settings.YOOKASSA_SHOP_ID_BOT
            Configuration.secret_key = settings.YOOKASSA_SECRET_BOT

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
                }
            }, )

            request.session['yookassa_payment_id'] = payment.id
            request.session['yookassa_payment_amount'] = float(amount)

            Transaction.objects.create(status='pending', paid=False, amount=amount, user=request.user.profile.telegram_user,
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
            return redirect('test_profile')

class TestPaymentSuccessView(TemplateView):
    template_name = 'payments/payment_success.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class TestPaymentFailureView(TemplateView):
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
            Logging.objects.create(log_level="SUCCESS", message=f'[WEB] [TEST] [Приём вебхука] [{event_type}]',
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
                        telegram_user.save()
                    else:
                        telegram_user.subscription_status = True
                        telegram_user.subscription_expiration = datetime.now() + timedelta(days=days)
                        telegram_user.payment_method_id = payment_method_id
                        telegram_user.save()

                    referred_list = [x for x in TelegramReferral.objects.filter(referred=telegram_user)]
                    if referred_list:
                        for r in referred_list:
                            user_to_pay = TelegramUser.objects.filter(user_id=r.referrer.user_id).first()
                            level = r.level
                            percent = None
                            if level == 1:
                                percent = ReferralSettings.objects.get(pk=1).level_1_percentage
                            elif level == 2:
                                percent = ReferralSettings.objects.get(pk=1).level_2_percentage
                            elif level == 3:
                                percent = ReferralSettings.objects.get(pk=1).level_3_percentage
                            elif level == 4:
                                percent = ReferralSettings.objects.get(pk=1).level_4_percentage
                            elif level == 5:
                                percent = ReferralSettings.objects.get(pk=1).level_5_percentage
                            if percent:
                                income = float(TelegramUser.objects.get(user_id=user_to_pay.user_id).income) + (
                                        float(amount_value) * float(percent) / 100)
                                telegram_user.income = income
                                telegram_user.save()

                    Logging.objects.create(log_level="SUCCESS",
                                           message=f'[BOT] [TEST] [Платёж  на сумму {str(amount_value)} р. прошёл]',
                                           datetime=datetime.now(), user=telegram_user)
                    return HttpResponse(f'Обновляем баланс пользователя', status=200)

            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[BOT] [TEST] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=telegram_user)
                return HttpResponse('OK', status=200)

        elif 'canceled' in str(event_type):
            Logging.objects.create(log_level="WARNING", message=f'[WEB] [TEST] [Приём вебхука] [{event_type}]',
                                   datetime=datetime.now())
            try:
                payment_id = payment_data.get('id')
                status = payment_data.get('status')
                transaction = Transaction.objects.filter(payment_id=payment_id).first()
                transaction.status = status
                transaction.paid = False
                transaction.save()
                Logging.objects.create(log_level="WARNING",
                                       message=f'[WEB] [TEST] [Платёж  на сумму {str(traceback.format_exc())} р. отменён]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            except Exception as e:
                Logging.objects.create(log_level="DANGER",
                                       message=f'[WEB] [TEST] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            return HttpResponse('OK', status=200)
        else:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] [TEST] [Непонятно что] [.......]',
                                   datetime=datetime.now())
            return HttpResponse('OK', status=200)
