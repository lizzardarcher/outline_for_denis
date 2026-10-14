
"""
CryptoCloud: создание инвойса (сайт) и POSTBACK webhook (site/bot).
"""

from __future__ import annotations

import traceback
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from apps.payment.cryptocloud_common import (
    apply_successful_pay,
    create_invoice,
    credentials_for_channel,
    find_transaction_from_postback,
    is_cryptocloud_allowed_for_user,
    json_ok,
    parse_postback_payload,
    payment_system_for_channel,
    verify_cryptocloud_jwt,
)

from bot.models import IncomeInfo, Logging, Transaction

def _user_email(telegram_user) -> str:
    try:
        return telegram_user.user_profile.user.email or "noemail@noemail.ru"
    except Exception:
        return "noemail@noemail.ru"


class CreateCryptoCloudPaymentView(LoginRequiredMixin, View):
    """Сайт: pending Transaction, инвойс CryptoCloud, редирект на link."""

    def post(self, request, *args, **kwargs):
        try:
            telegram_user = request.user.profile.telegram_user
            if not is_cryptocloud_allowed_for_user(telegram_user):
                return redirect("profile")

            from apps.payment.retention_offer import resolve_purchase_for_user
            amount, days = resolve_purchase_for_user(
                request.POST.get("subscription"), telegram_user
            )
            if amount <= 0 or days <= 0:
                return redirect("profile")

            api_key, shop_id, _secret = credentials_for_channel("site")
            if not api_key or not shop_id:
                Logging.objects.create(
                    category="payment",
                    log_level="DANGER",
                    message="[WEB] [CryptoCloud] Нет CRYPTOCLOUD_API_KEY_SITE / SHOP_ID_SITE",
                    datetime=datetime.now(),
                    user=telegram_user,
                )
                return redirect("profile")

            transaction = Transaction.objects.create(
                status="pending",
                paid=False,
                amount=Decimal(str(amount)),
                user=telegram_user,
                currency=getattr(settings, "CRYPTOCLOUD_CURRENCY", "RUB") or "RUB",
                income_info=IncomeInfo.objects.get(pk=1),
                side="Приход средств",
                description=f"Приобретение подписки (CryptoCloud SITE, {days} дн.)",
                payment_system="CryptoCloudSite",
            )

            invoice = create_invoice(
                channel="site",
                amount=amount,
                order_id=transaction.id,
                email=_user_email(telegram_user),
            )
            uuid = invoice.get("uuid")
            link = invoice.get("link")
            if uuid:
                transaction.payment_id = str(uuid)
                transaction.save(update_fields=["payment_id"])

            Logging.objects.create(
                category="payment",
                log_level="INFO",
                message=f"[WEB] [CryptoCloud] [Создан платёж tx={transaction.id} uuid={uuid} на {amount}]",
                datetime=datetime.now(),
                user=telegram_user,
            )
            if not link:
                raise RuntimeError("CryptoCloud: нет link в ответе create invoice")
            return redirect(link)
        except Exception:
            Logging.objects.create(
                category="payment",
                log_level="DANGER",
                message=f"[WEB] [CryptoCloud] [Ошибка create] {traceback.format_exc()}",
                datetime=datetime.now(),
            )
            return redirect("profile")


def _handle_postback(request, *, channel: str, log_prefix: str):
    data = parse_postback_payload(request)
    if not data:
        return HttpResponse("Invalid payload", status=400)

    _api_key, _shop_id, secret = credentials_for_channel(channel)
    token = data.get("token") or ""
    if not secret or not verify_cryptocloud_jwt(str(token), secret):
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=f"{log_prefix} [Webhook] Невалидный JWT",
            datetime=datetime.now(),
        )
        return HttpResponse("Invalid token", status=401)

    status = (data.get("status") or "").lower()
    invoice_info = data.get("invoice_info") or {}
    invoice_status = (invoice_info.get("invoice_status") or invoice_info.get("status") or "").lower()
    paid_ok = status in ("success", "paid") or invoice_status in ("success", "paid")
    if not paid_ok:
        return json_ok()

    transaction = find_transaction_from_postback(data)
    if not transaction:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=(
                f"{log_prefix} [Webhook] Транзакция не найдена "
                f"order_id={data.get('order_id')} invoice_id={data.get('invoice_id')}"
            ),
            datetime=datetime.now(),
        )
        return json_ok()

    expected_ps = payment_system_for_channel(channel)
    if transaction.payment_system and transaction.payment_system != expected_ps:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=(
                f"{log_prefix} [Webhook] payment_system={transaction.payment_system} "
                f"ожидали {expected_ps} tx={transaction.id}"
            ),
            datetime=datetime.now(),
        )
        return json_ok()

    telegram_user = transaction.user
    if not telegram_user:
        Logging.objects.create(
            category="payment",
            log_level="WARNING",
            message=f"{log_prefix} [Webhook] У tx={transaction.id} нет TelegramUser",
            datetime=datetime.now(),
        )
        return json_ok()

    payment_id = (
        (invoice_info.get("uuid") if isinstance(invoice_info, dict) else None)
        or data.get("invoice_id")
        or transaction.payment_id
        or str(transaction.id)
    )

    try:
        apply_successful_pay(
            transaction=transaction,
            telegram_user=telegram_user,
            payment_id=str(payment_id),
            channel=channel,
            log_prefix=log_prefix,
        )
    except Exception:
        Logging.objects.create(
            category="payment",
            log_level="DANGER",
            message=f"{log_prefix} [Ошибка webhook]\n{traceback.format_exc()}",
            datetime=datetime.now(),
            user=telegram_user,
        )
        return HttpResponse("processing error", status=500)
    return json_ok()


@method_decorator(csrf_exempt, name="dispatch")
class CryptoCloudSiteWebhookView(View):
    def post(self, request, *args, **kwargs):
        return _handle_postback(request, channel="site", log_prefix="[CRYPTOCLOUD-SITE]")


@method_decorator(csrf_exempt, name="dispatch")
class CryptoCloudBotWebhookView(View):
    def post(self, request, *args, **kwargs):
        return _handle_postback(request, channel="bot", log_prefix="[CRYPTOCLOUD-BOT]")


class CryptoCloudSuccessView(TemplateView):
    template_name = "payments/payment_success.html"


class CryptoCloudFailView(TemplateView):
    template_name = "payments/payment_failure.html"
