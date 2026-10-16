
"""
Окно автосписания: последний день подписки или уже просрочено.

Дата окончания включительная: в этот день ключи ещё живы, на следующий
update_user_subscription_status гасит статус и удаляет ключи.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from bot.models import Transaction

PENDING_KEY_GRACE = timedelta(hours=48)


def renewal_due_q(today=None):
    """
    Кого пора списывать, плюс уже неактивные (повтор после отказа и починка статуса).

    Активные с датой строго в будущем в выборку не попадают.
    """
    today = today or timezone.localdate()
    return (
        Q(subscription_status=False)
        | Q(subscription_expiration__isnull=True)
        | Q(subscription_expiration__lte=today)
    )


def subscription_has_full_days_left(user, today=None) -> bool:
    """До последнего дня ещё есть хотя бы одни сутки."""
    exp = user.subscription_expiration
    if not exp:
        return False
    today = today or timezone.localdate()
    return exp > today


def fresh_pending_recurring_user_ids(now=None):
    """Пользователи со свежим незакрытым автосписанием: ключи пока не снимаем."""
    now = now or timezone.now()
    cutoff = now - PENDING_KEY_GRACE
    return set(
        Transaction.objects.filter(
            status="pending",
            paid=False,
            timestamp__gte=cutoff,
            user_id__isnull=False,
        ).filter(
            Q(description__icontains="екуррент")
            | (
                Q(robokassa_recurring_previous_inv_id__isnull=False)
                & ~Q(robokassa_recurring_previous_inv_id="")
            )
        ).values_list("user_id", flat=True)
    )
