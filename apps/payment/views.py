# your_app/views.py
import logging
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from urllib3 import request

from django.contrib import messages
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import reverse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from yookassa import Configuration, Payment
import hashlib, hmac, json
from django.http import HttpResponse
from bot.models import TelegramUser, Transaction, IncomeInfo

logger = logging.getLogger(__name__)


class CreatePaymentView(View):
    def post(self, request, *args, **kwargs):

        # получаем сумму из POST, вы можете сделать по другому
        amount = request.POST.get('amount')
        try:
            amount = float(amount)
        except ValueError:
            logger.debug( "invalid amount")
            return HttpResponse('Неправильная сумма', status=400)

        # Получаем текущего пользователя
        user = request.user
        # Получаем профиль пользователя Django, связанный с пользователем Telegram.
        try:
            telegram_user = user.profile.telegram_user
        except Exception as e:
            logger.debug( f"Cant find Telegram user: {e}")
            return HttpResponse('Пользователь не найден', status=400)

        # Настройка ЮKassa
        Configuration.account_id = int(settings.YOOKASSA_SHOP_ID)
        Configuration.secret_key = settings.YOOKASSA_SECRET

        # Создание платежа
        payment = Payment.create({
            "amount": {
                "value": amount,
                "currency": "RUB"  # Валюта платежа
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f'https://domvpn.ru/payment/payment-success/?id=&date={datetime.now()}&amount={amount}',  # URL Успеха
                "enforce": False  # Это нужно для избежания некоторых ошибок редиректа.
            },
            "capture": True,  # Автоматическое списание средств
            "description": settings.YOOKASSA_PAYMENT_DESCRIPTION,
            # Тут можно указать id вашего пользователя
            "metadata": {
                'user_id': request.user.id,
                'telegram_user_id': request.user.profile.telegram_user.id,
            }
        },
        )

        Transaction.objects.create(status='pending', paid=False, amount=amount, user=request.user.profile.telegram_user,
                                   currency='RUB', income_info=IncomeInfo.objects.get(pk=1), side='Приход средств',
                                   description='Пополнение баланса пользователя', payment_id=payment.id)

        # Сохраняем payment_id в сессию (потом понадобится)
        # request.session['yookassa_payment_id'] = payment.id
        # Сохраняем сумму в сессию, чтобы потом понять, на какую сумму пользователь пополнил баланс
        # request.session['yookassa_payment_amount'] = float(amount)
        # Перенаправляем пользователя на страницу ЮKassa
        return redirect(payment.confirmation.confirmation_url)


class PaymentSuccessView(TemplateView):
    template_name = 'payments/payment_success.html'
    # def get(self, request, *args, **kwargs):
    #
    #     # получаем id платежа из сессии
    #     payment_id = request.session.get('yookassa_payment_id')
    #     amount = request.session.get('yookassa_payment_amount')
    #     # if payment_id is None or amount is None:
    #     #     return HttpResponse(f"Произошла ошибка при оплате. Попробуйте позже. {payment_id} {amount}", status=400)
    #
    #     # Настройка ЮKassa
    #     Configuration.account_id = int(settings.YOOKASSA_SHOP_ID)
    #     Configuration.secret_key = settings.YOOKASSA_SECRET
    #
    #     # Получаем данные о платеже
    #     try:
    #         payment = Payment.find_one(payment_id)
    #     except Exception as e:
    #         logger.debug( f"Cant get payment info: {e}")
    #         return HttpResponse(f"Произошла ошибка при оплате. Попробуйте позже. {str(e)}", status=400)
    #
    #     if payment.status == 'succeeded':
    #         logger.debug( f"Payment {payment_id} succeeded")
    #         user = request.user  # django пользователь
    #         telegram_user = user.profile.telegram_user  # пользователь telegram
    #
    #         # обновляем баланс пользователя в бд
    #         telegram_user.balance += amount
    #         telegram_user.save()
    #
    #         # Очищаем сессию
    #         del request.session['yookassa_payment_id']
    #         del request.session['yookassa_payment_amount']
    #
    #         # Перенаправляем на страницу успеха
    #         return render(request, 'payments/payment_success.html')
    #
    #     else:
    #         logger.debug( f"Payment {payment_id} failed")
    #         return redirect(reverse('payment_failure'))


class PaymentFailureView(View):
    def get(self, request, *args, **kwargs):
        # Возвращаем пользователя на страницу неудачи
        return render(request, 'payments/payment_failure.html')


@method_decorator(csrf_exempt, name='dispatch')
class YookassaWebhookView(View):
    def post(self, request, *args, **kwargs):
        """
        {'type': 'notification',
         'event': 'payment.succeeded',
          'object':
                {'id': '2f2d421d-000f-5000-9000-1ab151d5d70a',
                 'status': 'succeeded',
                  'amount':
                        {'value': '51.00',
                         'currency': 'RUB'},
                         'income_amount':
                            {'value': '49.21',
                             'currency': 'RUB'},
                             'description': 'Ð\x9fÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ Ð±Ð°Ð»Ð°Ð½Ñ\x81Ð° Ð¿Ð¾Ð»Ñ\x8cÐ·Ð¾Ð²Ð°Ñ\x82ÐµÐ»Ñ\x8f',
                             'recipient': {'account_id': '1022620', 'gateway_id': '2395585'},
                              'payment_method': {'type': 'yoo_money', 'id': '2f2d421d-000f-5000-9000-1ab151d5d70a',
                              'saved': False, 'status': 'inactive', 'title': 'YooMoney wallet 410011758831136', 'account_number': '410011758831136'},
                              'captured_at': '2025-01-30T07:46:41.994Z', 'created_at': '2025-01-30T07:46:37.008Z', 'test': True, 'refunded_amount':
                              {'value': '0.00', 'currency': 'RUB'}, 'paid': True, 'refundable': True,
                               'metadata': {'user_id': '5566146968', 'cms_name': 'yookassa_sdk_python', 'telegram_user_id': '5234'}}}

        """

        # Получаем данные из запроса
        body = request.body
        # signature = request.headers.get('X-YooKassa-Signature')
        # logger.debug( f"Webhook request: {body}, signature: {signature}")

        # Проверка подписи
        # if not self.check_signature(body, signature):
        #     logger.debug( f"Invalid signature")
        #     return HttpResponse('Invalid signature', status=400)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.debug( "Failed to decode json body")
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
            logger.info(f"Unhandled event type: {event_type}")
            return HttpResponse('OK', status=200)

    def check_signature(self, body, signature):
        """ Проверка подписи Yookassa """
        secret = settings.YOOKASSA_SECRET
        string_to_sign = body
        key = secret.encode('utf-8')
        message = string_to_sign.encode('utf-8')
        calculated_signature = hmac.new(key, message, hashlib.sha256).hexdigest()
        # logger.debug( f"calculated signature: {calculated_signature}")
        if calculated_signature == signature:
            return True
        return False

    def handle_successful_payment(self, payment_data):
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        metadata = payment_data.get('metadata')
        amount_value = float(payment_data.get('amount').get('value'))
        # logger.debug( f"Success payment webhook, id: {payment_id}, status:{status}, metadata: {metadata}")

        # Настройка ЮKassa
        # Configuration.account_id = int(settings.YOOKASSA_SHOP_ID)
        # Configuration.secret_key = settings.YOOKASSA_SECRET

        # Получаем данные о платеже
        # try:
        #     payment = Payment.find_one(payment_id)
        # except Exception as e:
        #     logger.debug( f"Cant get payment info: {e}")
        #     return HttpResponse(f'Cant get payment info {str(e)} BAD', status=401)
        #
        try:
            user_id = int(metadata.get('user_id'))
            telegram_user_id = int(metadata.get('telegram_user_id'))
        except Exception as e:
            logger.debug( f"Cant read metadata: {e}")
            return HttpResponse(f'Cant read metadata {str(e)} BAD', status=401)

        # Обновляем баланс пользователя
        try:
            telegram_user = TelegramUser.objects.get(id=telegram_user_id)
            telegram_user.balance = float(telegram_user.balance) + float(amount_value)
            telegram_user.save()

            transaction = Transaction.objects.filter(payment_id=payment_id).first()
            transaction.status = status
            transaction.save()

            income = IncomeInfo.objects.get(id=1)
            income.total_amount = float(income.total_amount) + float(amount_value)
            income.save()
            return HttpResponse(f'Обновляем баланс пользователя', status=200)
        except Exception as e:
            logger.error(f"Cant find or update Transaction : {str(e)}")

    def handle_canceled_payment(self, payment_data):
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        logger.debug( f"Canceled payment webhook, id: {payment_id}, status:{status}")

