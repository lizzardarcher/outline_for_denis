# your_app/views.py
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import reverse
from yookassa import Configuration, Payment
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import hashlib, hmac, json
from django.http import HttpResponse
from bot.models import TelegramUser

logger = logging.getLogger(__name__)


@method_decorator(login_required, name='dispatch')
class CreatePaymentView(View):
    def post(self, request, *args, **kwargs):
        # получаем сумму из POST, вы можете сделать по другому
        amount = request.POST.get('amount', '100.00')
        try:
            amount = float(amount)
        except ValueError:
            logger.error("invalid amount")
            return HttpResponse('Неправильная сумма', status=400)

        # Получаем текущего пользователя
        user = request.user
        # Получаем профиль пользователя Django, связанный с пользователем Telegram.
        try:
            telegram_user = user.profile.telegram_user
        except Exception as e:
            logger.error(f"Cant find Telegram user: {e}")
            return HttpResponse('Пользователь не найден', status=400)

        # Настройка ЮKassa
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

        # Создание платежа
        payment = Payment.create({
            "amount": {
                "value": amount,
                "currency": "RUB"  # Валюта платежа
            },
            "confirmation": {
                "type": "redirect",
                "return_url": request.build_absolute_uri(reverse('payment_success')),  # URL Успеха
                "enforce": False  # Это нужно для избежания некоторых ошибок редиректа.
            },
            "capture": True,  # Автоматическое списание средств
            "description": settings.YOOKASSA_PAYMENT_DESCRIPTION,
            # Тут можно указать id вашего пользователя
            "metadata": {
                'user_id': user.id,
                'telegram_user_id': telegram_user.id,
            }
        },
        )

        # Сохраняем payment_id в сессию (потом понадобится)
        request.session['yookassa_payment_id'] = payment.id
        # Сохраняем сумму в сессию, чтобы потом понять, на какую сумму пользователь пополнил баланс
        request.session['yookassa_payment_amount'] = float(amount)
        # Перенаправляем пользователя на страницу ЮKassa
        return redirect(payment.confirmation.confirmation_url)
    
@method_decorator(login_required, name='dispatch')
class PaymentSuccessView(View):
    def get(self, request, *args, **kwargs):

        # получаем id платежа из сессии
        payment_id = request.session.get('yookassa_payment_id', None)
        amount = request.session.get('yookassa_payment_amount', None)
        if payment_id is None or amount is None:
            return HttpResponse("Произошла ошибка при оплате. Попробуйте позже.", status=400)

        # Настройка ЮKassa
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

        # Получаем данные о платеже
        try:
            payment = Payment.find_one(payment_id)
        except Exception as e:
            logger.error(f"Cant get payment info: {e}")
            return HttpResponse("Произошла ошибка при оплате. Попробуйте позже.", status=400)

        if payment.status == 'succeeded':
            logger.info(f"Payment {payment_id} succeeded")
            user = request.user  # django пользователь
            telegram_user = user.profile.telegram_user  # пользователь telegram

            # обновляем баланс пользователя в бд
            telegram_user.balance += amount
            telegram_user.save()

            # Очищаем сессию
            del request.session['yookassa_payment_id']
            del request.session['yookassa_payment_amount']

            # Перенаправляем на страницу успеха
            return render(request, 'payment_success.html')  # Создайте payment_success.html

        else:
            logger.error(f"Payment {payment_id} failed")
            return redirect(reverse('payment_failure'))


@method_decorator(login_required, name='dispatch')
class PaymentFailureView(View):
    def get(self, request, *args, **kwargs):
        # Возвращаем пользователя на страницу неудачи
        return render(request, 'payment_failure.html')  # Создайте payment_failure.html



@method_decorator(csrf_exempt, name='dispatch')
class YookassaWebhookView(View):
    def post(self, request, *args, **kwargs):
        # Получаем данные из запроса
        body = request.body.decode('utf-8')
        signature = request.headers.get('X-YooKassa-Signature')
        logger.debug(f"Webhook request: {body}, signature: {signature}")

        # Проверка подписи
        if not self.check_signature(body, signature):
            logger.error(f"Invalid signature")
            return HttpResponse('Invalid signature', status=400)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Failed to decode json body")
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
        secret = settings.YOOKASSA_WEBHOOK_SECRET_KEY
        string_to_sign = body
        key = secret.encode('utf-8')
        message = string_to_sign.encode('utf-8')
        calculated_signature = hmac.new(key, message, hashlib.sha256).hexdigest()
        logger.debug(f"calculated signature: {calculated_signature}")
        if calculated_signature == signature:
            return True
        return False

    def handle_successful_payment(self, payment_data):
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        metadata = payment_data.get('metadata')
        amount_value = float(payment_data.get('amount').get('value'))
        logger.debug(f"Success payment webhook, id: {payment_id}, status:{status}, metadata: {metadata}")

        # Настройка ЮKassa
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
        # Получаем данные о платеже
        try:
            payment = Payment.find_one(payment_id)
        except Exception as e:
            logger.error(f"Cant get payment info: {e}")
            return

        if payment.status != "succeeded":
            logger.error(f"Payment {payment_id} is not succeeded")
            return

        try:
            user_id = int(metadata.get('user_id'))
            telegram_user_id = int(metadata.get('telegram_user_id'))
        except Exception as e:
            logger.error(f"Cant read metadata: {e}")
            return

        # Обновляем баланс пользователя
        try:
            telegram_user = TelegramUser.objects.get(id=telegram_user_id)
            telegram_user.balance += amount_value
            telegram_user.save()
            logger.info(f"Updated balance for telegram_user: {telegram_user.id}, new balance:{telegram_user.balance}")

        except Exception as e:
            logger.error(f"Cant find or update Telegram user : {e}")
            return

    def handle_canceled_payment(self, payment_data):
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        logger.info(f"Canceled payment webhook, id: {payment_id}, status:{status}")
