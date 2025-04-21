import traceback

from celery import shared_task
from django.utils import timezone

from telebot import TeleBot

from bot.main.outline_client import sync_delete_user_keys
from bot.main.utils import msg
from bot.main.vless.MarzbanAPI import MarzbanAPI
from bot.models import Logging, Transaction, IncomeInfo, TelegramUser, TelegramBot, VpnKey
from bot.models import Server

@shared_task
def create_log_entry():
    Logging.objects.create(
        log_level='DEBUG',
        message='CELERY TASKS TESTING'
    )
    return None

@shared_task
def update_generated_keys(*args, **kwargs):
    """
    Updating keys generated
    :return: None
    """
    servers = Server.objects.all()
    for server in servers:
        server.keys_generated = server.vpnkey_set.all().count()
        server.save()
    return None

@shared_task
def update_total_income(*args, **kwargs):
    """
    Updating total income
    :param args:
    :param kwargs:
    """
    transactions = Transaction.objects.filter(status='succeeded')
    income_info = IncomeInfo.objects.get(pk=1)
    total_amount = float(0)
    for transaction in transactions:
        total_amount += float(transaction.amount)
    income_info.total_amount = total_amount
    income_info.save()
    return None


@shared_task
def update_user_subscription_status():
    """
    Updates user subscription status based on expiration and deletes VPN keys.
    This function is now synchronous and suitable for Celery tasks.
    """
    bot = TeleBot(token=TelegramBot.objects.all().first().token)

    users = TelegramUser.objects.filter(subscription_expiration__lt=timezone.now(), subscription_status=True)
    for user in users:
        try:
            user.subscription_status = False
            user.save()
            try:
                bot.send_message(chat_id=user.user_id, text=msg.subscription_expired)
            except:
                pass

            Logging.objects.create(log_level='WARNING', message='[BOT] [Закончилась подписка у пользователя]',
                              datetime=timezone.now(), user=user)
        except Exception as e:
            Logging.objects.create(log_level='FATAL',
                              message=f'[BOT] [Ошибка при автообновлении статуса подписки:\n{traceback.format_exc()}]',
                              datetime=timezone.now())

    vpn_keys = VpnKey.objects.filter(user__subscription_status=False)
    for key in vpn_keys:
        if key.protocol == 'outline':
            try:
                sync_delete_user_keys(user=key.user)
            except Exception:
                pass

        elif key.protocol == 'vless':
            try:
                MarzbanAPI().delete_user(username=str(key.user.user_id))
                key.delete()
            except Exception:
                pass

