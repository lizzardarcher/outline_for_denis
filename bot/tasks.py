import traceback

import paramiko
from celery import shared_task
from django.utils import timezone
from django.contrib.admin.models import LogEntry

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.main.utils import msg
from bot.main.vless.MarzbanAPI import MarzbanAPI
from bot.models import Logging, Transaction, IncomeInfo, TelegramUser, TelegramBot, VpnKey, TelegramMessage
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
        try:
            MarzbanAPI().delete_user(username=str(key.user.user_id))
            key.delete()
        except Exception:
            Logging.objects.create(log_level='FATAL',
                                   message=f'[BOT] [Ошибка при удалении ключа:\n{traceback.format_exc()}]',
                                   datetime=timezone.now())


@shared_task
def message_sender():
    messages = TelegramMessage.objects.filter(status='not_sent')
    bot = TeleBot(token=TelegramBot.objects.all().first().token)
    _markup = InlineKeyboardMarkup().add(InlineKeyboardButton(text=f'💡 Управление VPN', callback_data=f'manage'))
    counter = 0
    for message in messages:

        users = []

        if message.send_to_subscribed:
            users += TelegramUser.objects.filter(subscription_status=True)
        elif message.send_to_notsubscribed:
            users += TelegramUser.objects.filter(subscription_status=False)
        else:
            users += TelegramUser.objects.all()

        for user in users:
            try:
                bot.send_message(chat_id=user.user_id, text=message.text, reply_markup=_markup)
                counter += 1
                message.counter = counter
                message.save()
            except Exception as e:
                ...

        message.status = 'sent'
        message.counter = counter
        message.save()


@shared_task
def reload_servers():
    servers = Server.objects.filter(hosting__contains='IS Hosting')
    for server in servers:
        try:
            Logging.objects.create(log_level='DEBUG', message=f'[CELERY] Reloading server {server.hosting}...')
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(server.ip_address, username=server.user, password=server.password)
            stdin, stdout, stderr = ssh.exec_command('sudo reboot')  # or any other command to reload the server
            ssh.close()
            Logging.objects.create(log_level='DEBUG', message=f'[CELERY] Reloading server {server.hosting}...Done')
        except Exception as e:
            Logging.objects.create(log_level='ERROR', message=f'[CELERY] {traceback.format_exc()}')
            pass


@shared_task
def clear_log_entry():
    try:
        log_entry = LogEntry.objects.all()
        if log_entry.exists():
            log_entry.delete()
    except Exception as e:
        pass