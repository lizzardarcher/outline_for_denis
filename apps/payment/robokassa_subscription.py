"""
Общая логика подписки, OpState и защиты от повторного рекуррентного списания RoboKassa.
Используется в Celery-задачах и ResultURL views.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings
from django.utils import timezone

from bot.models import Prices, TelegramUser, Transaction

ROBOKASSA_OPSTATE_EXT_URL = 'https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt'
ROBOKASSA_OPSTATE_URL = 'https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpState'

# https://docs.robokassa.ru/ru/xml-interfaces — State.Code
ROBOKASSA_PAID_STATE_CODES = frozenset({'50', '100'})
ROBOKASSA_CANCELED_STATE_CODES = frozenset({'10', '60'})
ROBOKASSA_PENDING_STATE_CODES = frozenset({'5', '20', '80'})

ROBOKASSA_RECURRING_COOLDOWN_DAYS = getattr(settings, 'ROBOKASSA_RECURRING_COOLDOWN_DAYS', 3)

RECURRING_CHARGE = 'charge'
RECURRING_SKIP = 'skip'
RECURRING_REPAIR_AND_SKIP = 'repair_and_skip'


def robokassa_md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest().upper()


def _xml_local_name(tag: str) -> str:
    if not tag:
        return ''
    return tag.split('}')[-1]


def _xml_find_child(parent, local_name: str):
    if parent is None:
        return None
    for child in parent:
        if _xml_local_name(child.tag) == local_name:
            return child
    return None


def _xml_child_text(parent, local_name: str) -> str:
    child = _xml_find_child(parent, local_name)
    if child is None:
        return ''
    return (child.text or '').strip()


def parse_robokassa_opstate_xml(xml_text) -> dict:
    """
    Разбор ответа OpState / OpStateExt (вложенный XML + namespace).

    Возвращает плоский dict: ResultCode, State, OutSum, OpKey, PaymentID, RoboxID.
    State — это State/Code (100 = оплачен, 5 = ещё не оплачен).

    RoboKassa часто отдаёт UTF-8 BOM. requests при неверной charset декодирует BOM
    как 'ï»¿' — оба варианта снимаем до парсинга.
    """
    if not xml_text:
        return {}
    if isinstance(xml_text, bytes):
        text = xml_text.decode('utf-8-sig')
    else:
        text = xml_text
        if text.startswith('\ufeff'):
            text = text.lstrip('\ufeff')
        # BOM, ошибочно декодированный как latin-1/cp1252
        if text.startswith('ï»¿'):
            text = text[3:]

    root = ET.fromstring(text)
    result_el = _xml_find_child(root, 'Result')
    state_el = _xml_find_child(root, 'State')
    info_el = _xml_find_child(root, 'Info')

    result_code = _xml_child_text(result_el, 'Code')
    state_code = _xml_child_text(state_el, 'Code')
    if not state_code and state_el is not None:
        state_code = (state_el.text or '').strip()

    op_key = _xml_child_text(info_el, 'OpKey')
    payment_id = (
        _xml_child_text(info_el, 'PaymentID')
        or _xml_child_text(info_el, 'TransactionID')
        or _xml_child_text(root, 'PaymentID')
        or op_key
    )
    parsed = {
        'ResultCode': result_code,
        'State': state_code,
        'OutSum': _xml_child_text(info_el, 'OutSum'),
        'OpKey': op_key,
        'PaymentID': payment_id,
        'IncSum': _xml_child_text(info_el, 'IncSum'),
        'IncCurrLabel': _xml_child_text(info_el, 'IncCurrLabel'),
    }
    if payment_id:
        parsed['RoboxID'] = payment_id
    return parsed


def classify_robokassa_opstate(parsed: Optional[dict]) -> str:
    """paid | canceled | pending | error | unknown"""
    if not parsed:
        return 'error'
    result_code = str(parsed.get('ResultCode') or '').strip()
    if result_code and result_code != '0':
        return 'error'
    state = str(parsed.get('State') or '').strip()
    if state in ROBOKASSA_PAID_STATE_CODES:
        return 'paid'
    if state in ROBOKASSA_CANCELED_STATE_CODES:
        return 'canceled'
    if state in ROBOKASSA_PENDING_STATE_CODES or not state:
        return 'pending'
    return 'unknown'


def fetch_robokassa_opstate(
    inv_id: str,
    merchant_login: str,
    password_2: str,
    timeout: int = 15,
) -> Optional[dict]:
    """Запрос OpStateExt, при сетевой/HTTP ошибке — запасной OpState."""
    signature = robokassa_md5(f"{merchant_login}:{inv_id}:{password_2}")
    params = {
        'MerchantLogin': merchant_login,
        'InvoiceID': str(inv_id),
        'Signature': signature,
    }
    for url in (ROBOKASSA_OPSTATE_EXT_URL, ROBOKASSA_OPSTATE_URL):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            # content + utf-8-sig: RoboKassa BOM ломает resp.text при неверном charset
            parsed = parse_robokassa_opstate_xml(resp.content)
            if parsed:
                return parsed
        except Exception:
            continue
    return None


def resolve_subscription_days(amount_value: Decimal) -> int:
    prices = Prices.objects.get(pk=1)
    amount_int = int(amount_value)
    if amount_int == prices.price_1:
        return 31
    if amount_int == prices.price_2:
        return 93
    if amount_int == prices.price_3:
        return 184
    if amount_int == prices.price_4:
        return 366
    if amount_int == prices.price_5:
        return 3
    return 0


def extend_telegram_user_subscription(telegram_user: TelegramUser, days: int) -> None:
    """Продлевает подписку; безопасен при subscription_expiration=None."""
    if days <= 0:
        return
    today = timezone.now().date()
    if telegram_user.subscription_status:
        base = telegram_user.subscription_expiration or today
        telegram_user.subscription_expiration = base + timedelta(days=days)
    else:
        telegram_user.subscription_status = True
        telegram_user.subscription_expiration = today + timedelta(days=days)
    telegram_user.permission_revoked = False


def set_robokassa_recurring_parent_if_needed(telegram_user: TelegramUser, transaction: Transaction, inv_id) -> None:
    if not transaction.robokassa_is_recurring_parent:
        return
    if (telegram_user.robokassa_recurring_parent_inv_id or '').strip():
        return
    telegram_user.robokassa_recurring_parent_inv_id = str(inv_id)


def subscription_covers_today(telegram_user: TelegramUser) -> bool:
    exp = telegram_user.subscription_expiration
    if not exp:
        return False
    return exp >= timezone.now().date()


def subscription_needs_repair(telegram_user: TelegramUser) -> bool:
    if telegram_user.permission_revoked:
        return False
    today = timezone.now().date()
    if subscription_covers_today(telegram_user):
        return not telegram_user.subscription_status
    return True


def repair_subscription_from_transaction(transaction: Transaction) -> bool:
    """
    Дозаполняет подписку, если платёж succeeded, но пользователь не получил доступ.
    Идемпотентен: повторный вызов безопасен.
    """
    if transaction.status != 'succeeded' or not transaction.paid:
        return False
    telegram_user = transaction.user
    if not telegram_user or telegram_user.permission_revoked:
        return False

    today = timezone.now().date()
    if subscription_covers_today(telegram_user):
        if not telegram_user.subscription_status:
            telegram_user.subscription_status = True
            telegram_user.save(update_fields=['subscription_status'])
            return True
        return False

    days = resolve_subscription_days(transaction.amount)
    if days <= 0:
        return False

    today = timezone.now().date()
    telegram_user.subscription_status = True
    telegram_user.subscription_expiration = today + timedelta(days=days)
    telegram_user.permission_revoked = False
    set_robokassa_recurring_parent_if_needed(
        telegram_user,
        transaction,
        transaction.robokassa_invoice_id or transaction.id,
    )
    telegram_user.save()
    return True


def verify_robokassa_recurring_parent(user: TelegramUser, parent_inv: str, payment_system: str) -> bool:
    """Parent InvId должен быть успешным платежом в том же магазине (Bot/Site)."""
    return Transaction.objects.filter(
        user=user,
        robokassa_invoice_id=parent_inv,
        payment_system=payment_system,
        status='succeeded',
        paid=True,
    ).exists()


def _has_pending_recurring_charge(user: TelegramUser, payment_system: str) -> bool:
    """Любой незакрытый рекуррент блокирует новое списание, без TTL."""
    return Transaction.objects.filter(
        user=user,
        payment_system=payment_system,
        status='pending',
        paid=False,
        robokassa_recurring_previous_inv_id__isnull=False,
    ).exclude(robokassa_recurring_previous_inv_id='').exists()


def _recent_succeeded_payment(user: TelegramUser, payment_system: str):
    cutoff = timezone.now() - timedelta(days=ROBOKASSA_RECURRING_COOLDOWN_DAYS)
    return (
        Transaction.objects.filter(
            user=user,
            payment_system=payment_system,
            status='succeeded',
            paid=True,
            timestamp__gte=cutoff,
        )
        .order_by('-timestamp')
        .first()
    )


def evaluate_robokassa_recurring_charge(user: TelegramUser, payment_system: str) -> tuple[str, str]:
    """
    Возвращает (action, reason):
      charge — можно инициировать рекуррент;
      skip — пропустить;
      repair_and_skip — восстановить подписку без списания.
    """
    if user.permission_revoked:
        return RECURRING_SKIP, 'permission_revoked'

    if subscription_covers_today(user):
        if not user.subscription_status:
            user.subscription_status = True
            user.save(update_fields=['subscription_status'])
        return RECURRING_REPAIR_AND_SKIP, 'subscription_expiration в будущем'

    if _has_pending_recurring_charge(user, payment_system):
        return RECURRING_SKIP, 'есть pending рекуррент'

    recent = _recent_succeeded_payment(user, payment_system)
    if recent:
        if subscription_needs_repair(user):
            repair_subscription_from_transaction(recent)
        return RECURRING_REPAIR_AND_SKIP, f'недавний успешный платёж (tx={recent.id})'

    return RECURRING_CHARGE, ''
