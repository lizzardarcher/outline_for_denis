import os
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_for_denis.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

from datetime import datetime

from bot.models import *


def ukassa_site_attempt_recurring_payment():
    """
    Периодическая задача для списания средств с пользователей,
    у которых статус подписки False и есть payment_method_id.
    """
    users_to_charge = TelegramUser.objects.filter(subscription_status=False, payment_method_id__isnull=False,
                                                  payment_method_id__gt='', permission_revoked=False)

    print(f'[CELERY] [SITE] [Списание] [Начало] [количество пользователей: {users_to_charge.count()}]')

    for user in users_to_charge:
        if user.payment_method_id:

            try:
                payment_system = Transaction.objects.filter(payment_id=user.payment_method_id).last().payment_system

                if payment_system != 'YooKassaSite':
                    continue

                print(f'Need to pay {user} {user.payment_method_id}')
            except Exception as e:
                print(f"error: {e}")
    print(f"[CELERY] [SITE] [Списание] [Конец]")
ukassa_site_attempt_recurring_payment()