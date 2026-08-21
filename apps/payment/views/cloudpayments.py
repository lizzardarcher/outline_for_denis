
"""
CloudPayments: создание платежа, страница виджета, webhooks Check/Pay/Fail.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.payment.cloudpayments_common import (
    apply_fail_side_effects,
    apply_successful_pay,
    credentials_for_channel,
    default_account_id,
    find_transaction_by_invoice,
    is_cloudpayments_allowed_django_user,
    is_cloudpayments_allowed_telegram_user,
    json_code,
    payment_system_for_channel,
    verify_cloudpayments_hmac,
)
from bot.models import IncomeInfo, Logging, Prices, TelegramUser, Transaction

WIDGET_SIGNER_SALT = "cloudpayments-widget"
WIDGET_SIGNER_MAX_AGE = 60 * 60 * 6  # 6 часов


def _resolve_amount_days(subscription) -> tuple[float, int]:
    prices = Prices.objects.get(pk=1)
    amount = 0.0
    days = 0
    if float(subscription) == float(prices.price_1):
        amount, days = float(prices.price_1), 31
    elif float(subscription) == float(prices.price_2):
        amount, days = float(prices.price_2), 93
    elif float(subscription) == float(prices.price_3):
        amount, days = float(prices.price_3), 184
    elif float(subscription) == float(prices.price_4):
        amount, days = float(prices.price_4), 366
    elif float(subscription) == float(prices.price_5):
        amount, days = float(prices.price_5), 3
    return amount, days


def _widget_context(
    request,
    transaction: Transaction,
    channel: str,
    telegram_user: TelegramUser,
) -> dict:
    public_id, _secret = credentials_for_channel(channel)
    email = "noemail@noemail.ru"
    try:
        email = telegram_user.user_profile.user.email or email
    except Exception:
        pass
    account_id = default_account_id(telegram_user)
    amount = float(transaction.amount)
    success_url = request.build_absolute_uri(reverse("payment_success"))
    fail_url = request.build_absolute_uri(reverse("payment_failure"))
    return {
        "widget_config": {
            "publicTerminalId": public_id,
            "amount": amount,
            "currency": "RUB",
            "description": transaction.description or f"Подписка DomVPN (tx {transaction.id})",
            "externalId": str(transaction.id),
            "accountId": account_id,
            "email": email,
            "successUrl": success_url,
            "failUrl": fail_url,
        },
        "channel": channel,
        "is_test": getattr(settings, "CLOUDPAYMENTS_IS_TEST", True),
        "transaction_id": transaction.id,
    }


def make_bot_widget_token(transaction_id: int, user_id: int) -> str:
    return signing.dumps(
        {"tx": transaction_id, "uid": user_id},
        salt=WIDGET_SIGNER_SALT,
    )


def load_bot_widget_token(token: str) -> dict:
    return signing.loads(token, salt=WIDGET_SIGNER_SALT, max_age=WIDGET_SIGNER_MAX_AGE)


class CreateCloudPaymentsPaymentView(LoginRequiredMixin, View):
    """Сайт: создаёт pending Transaction и редиректит на страницу виджета."""

    def post(self, request, *args, **kwargs):
        if not is_cloudpayments_allowed_django_user(request.user):
            return HttpResponseForbidden("CloudPayments временно недоступен")
        try:
            telegram_user = request.user.profile.telegram_user
            amount, days = _resolve_amount_days(request.POST.get("subscription"))
            if amount <= 0 or days <= 0:
                return redirect("profile")

            public_id, secret = credentials_for_channel("site")
            if not public_id or not secret:
                Logging.objects.create(
                    category="payment",
                    log_level="DANGER",
                    message="[WEB] [CloudPayments] Нет CLOUDPAYMENTS_PUBLIC_ID_SITE / API_SECRET_SITE",
                    datetime=datetime.now(),
                    user=telegram_user,
                )
                return redirect("profile")

            transaction = Transaction.objects.create(
                status="pending",
                paid=False,
                amount=Decimal(str(amount)),
                user=telegram_user,
                currency="RUB",
                income_info=IncomeInfo.objects.get(pk=1),
                side="Приход средств",
                description=f"Приобретение подписки (CloudPayments SITE, {days} дн.)",
                payment_system="CloudPaymentsSite",
            )
            if not (telegram_user.cloudpayments_account_id or "").strip():
                telegram_user.cloudpayments_account_id = default_account_id(telegram_user)
                telegram_user.save(update_fields=["cloudpayments_account_id"])

            Logging.objects.create(
                category="payment",
                log_level="INFO",
                message=f"[WEB] [CloudPayments] [Создан платёж tx={transaction.id} на {amount} р.]",
                datetime=datetime.now(),
                user=telegram_user,
            )
            return redirect(
                reverse("cloudpayments_widget_site") + f"?tx={transaction.id}"
            )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"[WEB] [CloudPayments] [Ошибка create] {traceback.format_exc()}",
                datetime=datetime.now(),
            )
            return redirect("profile")


class CloudPaymentsSiteWidgetView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        if not is_cloudpayments_allowed_django_user(request.user):
            return HttpResponseForbidden("CloudPayments временно недоступен")
        tx_id = request.GET.get("tx")
        telegram_user = request.user.profile.telegram_user
        transaction = get_object_or_404(
            Transaction,
            pk=tx_id,
            user=telegram_user,
            payment_system="CloudPaymentsSite",
        )
        if transaction.status == "succeeded":
            return redirect("payment_success")
        ctx = _widget_context(request, transaction, "site", telegram_user)
        return render(request, "payments/cloudpayments_widget.html", ctx)


class CloudPaymentsBotWidgetView(View):
    """Страница виджета для оплаты из Telegram (signed token)."""

    def get(self, request, *args, **kwargs):
        token = kwargs.get("token") or request.GET.get("token")
        if not token:
            return HttpResponseBadRequest("token required")
        try:
            payload = load_bot_widget_token(token)
        except signing.BadSignature:
            return HttpResponseForbidden("invalid or expired token")

        telegram_user = get_object_or_404(TelegramUser, user_id=payload["uid"])
        if not is_cloudpayments_allowed_telegram_user(telegram_user):
            return HttpResponseForbidden("CloudPayments временно недоступен")

        transaction = get_object_or_404(
            Transaction,
            pk=payload["tx"],
            user=telegram_user,
            payment_system="CloudPaymentsBot",
        )
        if transaction.status == "succeeded":
            return HttpResponse("Оплата уже прошла. Можно вернуться в бот.")

        ctx = _widget_context(request, transaction, "bot", telegram_user)
        bot_username = ""
        try:
            from bot.models import TelegramBot

            bot_username = (TelegramBot.objects.get(pk=1).username or "").lstrip("@")
        except Exception:
            pass
        if bot_username:
            tg_url = f"https://t.me/{bot_username}?start"
            ctx["widget_config"]["successUrl"] = tg_url
            ctx["widget_config"]["failUrl"] = tg_url
        return render(request, "payments/cloudpayments_widget.html", ctx)


class _CloudPaymentsWebhookBase(View):
    channel = "site"  # bot | site
    event = "pay"  # check | pay | fail

    def post(self, request, *args, **kwargs):
        raw_body = request.body or b""
        _public_id, api_secret = credentials_for_channel(self.channel)
        log_prefix = f"[{self.channel.upper()}] [CloudPayments] [{self.event}]"

        if not verify_cloudpayments_hmac(raw_body, api_secret, request):
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"{log_prefix} [HMAC не прошёл]",
                datetime=datetime.now(),
            )
            # Для Check отказ — code 13; для Pay/Fail всё равно отвечаем 0 после лога? Лучше 403
            # Документация: при неверной подписи не принимать. Отдаём code 13 для check.
            if self.event == "check":
                return json_code(13)
            return json_code(0)

        # form-urlencoded или JSON
        data = request.POST
        if not data:
            try:
                data = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                data = {}

        def g(key, default=""):
            if hasattr(data, "get"):
                return data.get(key, default)
            return default

        invoice_id = str(g("InvoiceId") or g("invoiceId") or "")
        account_id = str(g("AccountId") or g("accountId") or "")
        amount_raw = g("Amount") or g("PaymentAmount") or "0"
        try:
            amount_value = Decimal(str(amount_raw))
        except Exception:
            amount_value = Decimal("0")
        transaction_id = g("TransactionId") or g("transactionId") or ""
        token = str(g("Token") or "")
        status = str(g("Status") or "")
        reason_code_raw = g("ReasonCode")
        try:
            reason_code = int(reason_code_raw) if reason_code_raw not in (None, "") else None
        except (TypeError, ValueError):
            reason_code = None

        transaction = find_transaction_by_invoice(invoice_id)
        telegram_user = None
        if transaction and transaction.user_id:
            telegram_user = transaction.user
        elif account_id.startswith("tg:"):
            try:
                telegram_user = TelegramUser.objects.filter(
                    user_id=int(account_id.split(":", 1)[1])
                ).first()
            except ValueError:
                telegram_user = None
        elif account_id:
            telegram_user = TelegramUser.objects.filter(
                cloudpayments_account_id=account_id
            ).first()

        try:
            if self.event == "check":
                return self._handle_check(
                    transaction, amount_value, account_id, log_prefix
                )
            if self.event == "pay":
                return self._handle_pay(
                    transaction,
                    telegram_user,
                    amount_value,
                    transaction_id,
                    token,
                    status,
                    log_prefix,
                )
            if self.event == "fail":
                return self._handle_fail(
                    transaction, telegram_user, reason_code, log_prefix
                )
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"{log_prefix} [Ошибка] {traceback.format_exc()}",
                datetime=datetime.now(),
                user=telegram_user,
            )
        return json_code(0)

    def _handle_check(self, transaction, amount_value, account_id, log_prefix):
        if not transaction:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"{log_prefix} [Неверный InvoiceId]",
                datetime=datetime.now(),
            )
            return json_code(10)
        expected = Decimal(transaction.amount).quantize(Decimal("0.01"))
        got = Decimal(amount_value).quantize(Decimal("0.01"))
        if expected != got:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"{log_prefix} [Неверная сумма] expected={expected} got={got} tx={transaction.id}",
                datetime=datetime.now(),
                user=transaction.user,
            )
            return json_code(12)
        if account_id and transaction.user:
            expected_acc = default_account_id(transaction.user)
            if account_id != expected_acc and account_id != f"tg:{transaction.user.user_id}":
                Logging.objects.create(
                    category="payment",
                    log_level="WARNING",
                    message=f"{log_prefix} [Некорректный AccountId] {account_id}",
                    datetime=datetime.now(),
                    user=transaction.user,
                )
                return json_code(11)
        if transaction.status == "succeeded":
            # Уже оплачен — отклоняем повтор
            return json_code(13)
        return json_code(0)

    def _handle_pay(
        self,
        transaction,
        telegram_user,
        amount_value,
        payment_id,
        token,
        status,
        log_prefix,
    ):
        if status and status not in ("Completed", "Authorized", ""):
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"{log_prefix} [Неожиданный Status={status}]",
                datetime=datetime.now(),
                user=telegram_user,
            )
        if not transaction or not telegram_user:
            # Рекуррент мог создать tx; если InvoiceId потерян — ищем по payment_id
            if payment_id:
                transaction = Transaction.objects.filter(payment_id=str(payment_id)).first()
            if (not transaction or not telegram_user) and amount_value > 0 and telegram_user:
                # Создаём запись если charge без заранее созданного invoice (не должно быть)
                transaction = Transaction.objects.create(
                    status="pending",
                    paid=False,
                    amount=amount_value,
                    user=telegram_user,
                    currency="RUB",
                    income_info=IncomeInfo.objects.get(pk=1),
                    side="Приход средств",
                    description="Рекуррентный платёж (CloudPayments)",
                    payment_system=payment_system_for_channel(self.channel),
                    payment_id=str(payment_id) if payment_id else None,
                )
            elif not transaction or not telegram_user:
                Logging.objects.create(
                    category="payment",
                    log_level="DANGER",
                    message=f"{log_prefix} [Нет transaction/user] payment_id={payment_id}",
                    datetime=datetime.now(),
                )
                return json_code(0)

        apply_successful_pay(
            transaction=transaction,
            telegram_user=telegram_user,
            amount_value=amount_value if amount_value > 0 else Decimal(transaction.amount),
            payment_id=str(payment_id or transaction.payment_id or transaction.id),
            token=token,
            channel=self.channel,
            log_prefix=log_prefix,
        )
        return json_code(0)

    def _handle_fail(self, transaction, telegram_user, reason_code, log_prefix):
        if not telegram_user and transaction:
            telegram_user = transaction.user
        if telegram_user:
            apply_fail_side_effects(
                telegram_user=telegram_user,
                reason_code=reason_code,
                transaction=transaction,
                log_prefix=log_prefix,
            )
        else:
            Logging.objects.create(
                category="payment",
                log_level="WARNING",
                message=f"{log_prefix} [Fail без пользователя] ReasonCode={reason_code}",
                datetime=datetime.now(),
            )
        return json_code(0)


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsSiteCheckView(_CloudPaymentsWebhookBase):
    channel = "site"
    event = "check"


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsSitePayView(_CloudPaymentsWebhookBase):
    channel = "site"
    event = "pay"


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsSiteFailView(_CloudPaymentsWebhookBase):
    channel = "site"
    event = "fail"


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsBotCheckView(_CloudPaymentsWebhookBase):
    channel = "bot"
    event = "check"


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsBotPayView(_CloudPaymentsWebhookBase):
    channel = "bot"
    event = "pay"


@method_decorator(csrf_exempt, name="dispatch")
class CloudPaymentsBotFailView(_CloudPaymentsWebhookBase):
    channel = "bot"
    event = "fail"
