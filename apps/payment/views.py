# your_app/views.py
import traceback
from datetime import datetime

from django.views.generic import TemplateView

from django.shortcuts import redirect
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from yookassa import Configuration, Payment
import hashlib, hmac, json
from django.http import HttpResponse
from bot.models import TelegramUser, Transaction, IncomeInfo, Logging



class CreatePaymentView(View):
    def post(self, request, *args, **kwargs):

        # получаем сумму из POST, вы можете сделать по другому
        amount = request.POST.get('amount')
        try:
            amount = float(amount)
        except ValueError:
            return HttpResponse('Неправильная сумма', status=400)

        # Получаем текущего пользователя
        user = request.user
        # Получаем профиль пользователя Django, связанный с пользователем Telegram.
        try:
            telegram_user = user.profile.telegram_user
        except Exception as e:
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
        Logging.objects.create(log_level="INFO", message=f'[WEB] [Платёжный запрос на сумму {str(amount)} р.]',
                               datetime=datetime.now(), user=self.request.user.profile.telegram_user)
        return redirect(payment.confirmation.confirmation_url)


class PaymentSuccessView(TemplateView):
    template_name = 'payments/payment_success.html'


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
        try:
            telegram_user.balance = float(telegram_user.balance) + float(amount_value)
            telegram_user.save()

            transaction = Transaction.objects.filter(payment_id=payment_id).first()
            transaction.status = status
            transaction.paid = True
            transaction.save()

            income = IncomeInfo.objects.get(id=1)
            income.total_amount = float(income.total_amount) + float(amount_value)
            income.save()
            Logging.objects.create(log_level="SUCCESS", message=f'[WEB] [Платёж  на сумму {str(amount_value)} р. прошёл]', datetime=datetime.now(), user=telegram_user)
            return HttpResponse(f'Обновляем баланс пользователя', status=200)
        except Exception as e:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] [Ошибка при приёме вебхука {str(traceback.format_exc())}]',
                                   datetime=datetime.now(), user=telegram_user)

    def handle_canceled_payment(self, payment_data):
        try:
            payment_id = payment_data.get('id')
            status = payment_data.get('status')
            transaction = Transaction.objects.filter(payment_id=payment_id).first()
            transaction.status = status
            transaction.paid = False
            transaction.save()
            Logging.objects.create(log_level="WARNING", message=f'[WEB] [Платёж  на сумму {str(traceback.format_exc())} р. отменён]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)
        except Exception as e:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] [Ошибка при приёме вебхука {str(traceback.format_exc())}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)

