import traceback
from datetime import datetime, timedelta
from decimal import Decimal

import json
import requests

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from bot.models import (
    TelegramUser,
    Transaction,
    IncomeInfo,
    Logging,
    Prices,
    TelegramReferral,
    ReferralSettings,
    ReferralTransaction,
)


# ====== ХЕЛПЕРЫ ДЛЯ CRYPTOPAY API ======

def _cryptobot_create_invoice(
    api_key: str,
    amount: Decimal,
    asset: str,
    description: str,
    payload: str = None,
) -> dict:
    """
    Создание инвойса через CryptoBot (Crypto Pay API).
    ВНИМАНИЕ: структура URL/поля result зависят от версии API — обязательно
    сверься с официальной документацией CryptoBot и скорректируй при необходимости.
    """
    url = getattr(
        settings,
        "CRYPTOBOT_API_URL",
        "https://pay.crypt.bot/api/createInvoice",
    )

    headers = {
        "Crypto-Pay-API-Key": api_key,
        "Content-Type": "application/json",
    }

    data = {
        "amount": float(amount),  # CryptoBot ожидает число
        "asset": asset,          # Например: 'USDT', 'TON' и т.п.
        "description": description,
    }
    if payload is not None:
        data["payload"] = payload  # сюда можно положить id нашей Transaction

    resp = requests.post(url, json=data, headers=headers, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"CryptoBot error: {body}")
    return body["result"]  # ожидается, что тут есть pay_url и invoice_id


def _cryptobot_extract_update(data: dict):
    """
    Хелпер для webhook: вынимаем тип обновления и объект invoice.
    Структуру смотри в документации CryptoBot (здесь типичный пример).
    """
    update_type = data.get("update_type")
    invoice = data.get("invoice")
    return update_type, invoice


def _apply_subscription_and_referrals(
    *,
    telegram_user: TelegramUser,
    transaction: Transaction,
    amount_value: Decimal,
) -> None:
    """Повторяет логику из Yookassa/Robokassa: продление подписки + реферальные начисления."""
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

    # Подписка
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
        message=f"[CRYPTO] [Обработка платежа] [Сумма: {amount_value}] [Дни: {days}]",
        datetime=datetime.now(),
        user=telegram_user,
    )

    # Рефералка
    referral_percentages = {
        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
    }

    referred_list = TelegramReferral.objects.filter(
        referred=telegram_user
    ).select_related("referrer")

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
        message=f"[CRYPTO] [Платёж на сумму {amount_value} прошёл] [transaction_id={transaction.id}]",
        datetime=datetime.now(),
        user=telegram_user,
    )


# ====== САЙТ: СОЗДАНИЕ ПЛАТЕЖА ЧЕРЕЗ CRYPTOBOT ======

class CreateCryptoBotPaymentView(LoginRequiredMixin, View):
    """
    Аналог CreatePaymentView для CryptoBot:
      - определяем сумму/срок подписки
      - создаём Transaction(pending)
      - создаём инвойс через CryptoBot
      - сохраняем invoice_id в payment_id
      - редиректим пользователя на pay_url.
    """

    def post(self, request, *args, **kwargs):
        try:
            subscription = request.POST.get("subscription")

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

            telegram_user = request.user.profile.telegram_user

            transaction = Transaction.objects.create(
                status="pending",
                paid=False,
                amount=amount_decimal,
                user=telegram_user,
                currency=getattr(settings, "CRYPTOBOT_ASSET_SITE", "USDT"),
                income_info=IncomeInfo.objects.get(pk=1),
                side="Приход средств",
                description=f"Приобретение подписки (CryptoBot, {days} дн.)",
            )

            # создаём инвойс в CryptoBot
            asset = getattr(settings, "CRYPTOBOT_ASSET_SITE", "USDT")
            api_key = settings.CRYPTOBOT_API_KEY_SITE

            invoice = _cryptobot_create_invoice(
                api_key=api_key,
                amount=amount_decimal,
                asset=asset,
                description=f"Подписка DomVPN на {days} дн.",
                payload=str(transaction.id),  # можно потом использовать в webhook
            )

            pay_url = invoice["pay_url"]
            invoice_id = invoice.get("invoice_id")

            # сохраняем внешний invoice_id
            if invoice_id is not None:
                transaction.payment_id = str(invoice_id)
                transaction.save()

            Logging.objects.create(
                log_level="INFO",
                message=f"[WEB-CRYPTO] [Платёжный запрос на сумму {amount_decimal} {asset}]",
                datetime=datetime.now(),
                user=telegram_user,
            )

            return redirect(pay_url)

        except Exception:
            Logging.objects.create(
                log_level="DANGER",
                message=f"[WEB-CRYPTO] [Ошибка платёжного запроса {traceback.format_exc()}]",
                datetime=datetime.now(),
                user=request.user.profile.telegram_user if hasattr(request.user, "profile") else None,
            )
            return redirect("profile")


# ====== САЙТ: ВЕБХУК ОТ CRYPTOBOT ======

@method_decorator(csrf_exempt, name="dispatch")
class CryptoBotSiteWebhookView(View):
    """
    Webhook для инвойсов сайта.
    ВАЖНО: сюда нужно добавить проверки подлинности (подпись, IP и т.п.)
    согласно документации CryptoBot (они зависят от твоих настроек в личном кабинете).
    """

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON", status=400)

        # TODO: здесь добавить проверку подписи/секрета по доке CryptoBot
        # например, сравнивать секрет или подпись из заголовка/тела.

        update_type, invoice = _cryptobot_extract_update(data)
        if update_type != "invoice_paid" or not invoice:
            return HttpResponse("Ignored", status=200)

        invoice_id = str(invoice.get("invoice_id"))
        amount_value = Decimal(str(invoice.get("amount", "0")))
        asset = invoice.get("asset")  # например: 'USDT'

        # Пытаемся найти Transaction либо по payment_id, либо по payload
        transaction = Transaction.objects.filter(payment_id=invoice_id).first()

        # payload мы указывали = id транзакции
        if not transaction:
            payload = invoice.get("payload")
            if payload:
                try:
                    transaction = Transaction.objects.get(id=int(payload))
                except (Transaction.DoesNotExist, ValueError):
                    transaction = None

        if not transaction:
            Logging.objects.create(
                log_level="WARNING",
                message=f"[WEB-CRYPTO] [Webhook] Транзакция не найдена (invoice_id={invoice_id})",
                datetime=datetime.now(),
            )
            return HttpResponse("OK", status=200)

        # идемпотентность
        if transaction.status == "succeeded":
            return HttpResponse("OK", status=200)

        telegram_user = transaction.user
        if not telegram_user:
            Logging.objects.create(
                log_level="WARNING",
                message=f"[WEB-CRYPTO] [Webhook] У транзакции id={transaction.id} нет TelegramUser",
                datetime=datetime.now(),
            )
            return HttpResponse("OK", status=200)

        try:
            transaction.status = "succeeded"
            transaction.paid = True
            transaction.amount = amount_value
            transaction.currency = asset or transaction.currency or "CRYPTO"
            transaction.save()

            _apply_subscription_and_referrals(
                telegram_user=telegram_user,
                transaction=transaction,
                amount_value=amount_value,
            )

        except Exception:
            Logging.objects.create(
                log_level="DANGER",
                message=f"[WEB-CRYPTO] [Ошибка при обработке webhook]\n{traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )

        return HttpResponse("OK", status=200)


# ====== БОТ: ВЕБХУК ОТ CRYPTOBOT ДЛЯ БОТОВОГО МАГАЗИНА ======

@method_decorator(csrf_exempt, name="dispatch")
class CryptoBotBotWebhookView(View):
    """
    Webhook для крипто-инвойсов, созданных из Telegram-бота
    (используя CRYPTOBOT_API_KEY_BOT).
    Структура похожа на CryptoBotSiteWebhookView.
    """

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON", status=400)

        # TODO: добавить проверку подписи/секрета для ботового магазина (смотри доку CryptoBot)
        update_type, invoice = _cryptobot_extract_update(data)
        if update_type != "invoice_paid" or not invoice:
            return HttpResponse("Ignored", status=200)

        invoice_id = str(invoice.get("invoice_id"))
        amount_value = Decimal(str(invoice.get("amount", "0")))
        asset = invoice.get("asset")

        transaction = Transaction.objects.filter(payment_id=invoice_id).first()
        if not transaction:
            payload = invoice.get("payload")
            if payload:
                try:
                    transaction = Transaction.objects.get(id=int(payload))
                except (Transaction.DoesNotExist, ValueError):
                    transaction = None

        if not transaction:
            Logging.objects.create(
                log_level="WARNING",
                message=f"[BOT-CRYPTO] [Webhook] Транзакция не найдена (invoice_id={invoice_id})",
                datetime=datetime.now(),
            )
            return HttpResponse("OK", status=200)

        if transaction.status == "succeeded":
            return HttpResponse("OK", status=200)

        telegram_user = transaction.user
        if not telegram_user:
            Logging.objects.create(
                log_level="WARNING",
                message=f"[BOT-CRYPTO] [Webhook] У транзакции id={transaction.id} нет TelegramUser",
                datetime=datetime.now(),
            )
            return HttpResponse("OK", status=200)

        try:
            transaction.status = "succeeded"
            transaction.paid = True
            transaction.amount = amount_value
            transaction.currency = asset or transaction.currency or "CRYPTO"
            transaction.save()

            _apply_subscription_and_referrals(
                telegram_user=telegram_user,
                transaction=transaction,
                amount_value=amount_value,
            )

        except Exception:
            Logging.objects.create(
                log_level="DANGER",
                message=f"[BOT-CRYPTO] [Ошибка при обработке webhook]\n{traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )

        return HttpResponse("OK", status=200)


# ====== SUCCESS / FAIL ДЛЯ САЙТА (опционально) ======

class CryptoBotSuccessView(TemplateView):
    template_name = "payments/payment_success.html"


class CryptoBotFailView(TemplateView):
    template_name = "payments/payment_failure.html"