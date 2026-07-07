"""
Общая логика подписки и защиты от повторного рекуррентного списания RoboKassa.
Используется в Celery-задачах и ResultURL views.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from bot.models import Prices, TelegramUser, Transaction

ROBOKASSA_RECURRING_PENDING_HOURS = getattr(settings, 'ROBOKASSA_RECURRING_PENDING_HOURS', 72)
ROBOKASSA_RECURRING_COOLDOWN_DAYS = getattr(settings, 'ROBOKASSA_RECURRING_COOLDOWN_DAYS', 3)

RECURRING_CHARGE = 'charge'
RECURRING_SKIP = 'skip'
RECURRING_REPAIR_AND_SKIP = 'repair_and_skip'

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
    cutoff = timezone.now() - timedelta(hours=ROBOKASSA_RECURRING_PENDING_HOURS)
    return Transaction.objects.filter(
        user=user,
        payment_system=payment_system,
        status='pending',
        paid=False,
        timestamp__gte=cutoff,
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
