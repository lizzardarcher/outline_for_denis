import traceback


import paramiko
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.contrib.admin.models import LogEntry

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from apps.mtproxy.tasks import revoke_mtproxy_keys_for_user_task

from apps.payment.subscription_window import fresh_pending_recurring_user_ids
from bot.main.celerity_key_issue import try_delete_celerity_user
from bot.main.pasarguard_key_issue import try_delete_pasarguard_user
from bot.main.utils import msg
from bot.main.MarzbanAPI import MarzbanAPI
from bot.main.pasarguard_node_bootstrap import bootstrap_pasarguard_for_server
from bot.main.celerity_node_bootstrap import bootstrap_celerity_for_server
from bot.main.marzban_node_bootstrap import bootstrap_marzban_for_server
from bot.main.server_provision import provision_marzban_then_celerity, servers_pending_marzban_or_celerity
from bot.models import Logging, Transaction, IncomeInfo, TelegramUser, TelegramBot, VpnKey, TelegramMessage
from bot.models import Server



def _init_marzban_single_server(server: Server, cloud_init: str = "") -> bool:
    """Совместимость: cloud_init больше не используется, установка идёт официальным compose."""
    del cloud_init
    label = server.hosting or server.ip_address or f"pk={server.pk}"

    def _log(level: str, message: str) -> None:
        Logging.objects.create(
            category="vpn",
            log_level=level,
            message=f"[CELERY] [ss/vless] [{label}] {message}",
        )

    ok, _detail = bootstrap_marzban_for_server(server, log_fn=_log)
    return ok


@shared_task
def create_log_entry():
    Logging.objects.create(
        category='celery',
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
    grace_ids = fresh_pending_recurring_user_ids()

    users = TelegramUser.objects.filter(subscription_expiration__lt=timezone.now(), subscription_status=True)
    for user in users:
        try:
            if user.pk in grace_ids:
                Logging.objects.create(
                    category='bot',
                    log_level='INFO',
                    message='[BOT] [Подписка на паузе: есть свежий pending-рекуррент, ключи не снимаем]',
                    datetime=timezone.now(),
                    user=user,
                )
                continue
            user.subscription_status = False
            user.save()

            # revoke_mtproxy_keys_for_user_task.delay(user.user_id, reason="subscription_expired")
            try:
                bot.send_message(chat_id=user.user_id, text=msg.subscription_expired)
            except:
                pass

            Logging.objects.create(category='bot', log_level='WARNING', message='[BOT] [Закончилась подписка у пользователя]',
                                   datetime=timezone.now(), user=user)
        except Exception as e:
            Logging.objects.create(category='bot', log_level='FATAL',
                                   message=f'[BOT] [Ошибка при автообновлении статуса подписки:\n{traceback.format_exc()}]',
                                   datetime=timezone.now())

    vpn_keys = VpnKey.objects.filter(user__subscription_status=False).exclude(user_id__in=grace_ids)
    for key in vpn_keys:
        try:
            if getattr(settings, "VPN_MARZBAN_ENABLED", True):
                MarzbanAPI().delete_user(username=str(key.user.user_id))
            try_delete_pasarguard_user(key.user.user_id)
            try_delete_celerity_user(key.user.user_id)
            key.delete()
        except Exception:
            Logging.objects.create(category='bot', log_level='FATAL',
                                   message=f'[BOT] [Ошибка при удалении ключа:\n{traceback.format_exc()}]',
                                   datetime=timezone.now())



@shared_task
def message_sender():
    messages = TelegramMessage.objects.filter(status='not_sent')
    bot = TeleBot(token=TelegramBot.objects.all().first().token)
    _markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text='💡 Управление VPN', callback_data='manage'),
    )
    for message in messages:
        users = []
        if message.send_to_subscribed:
            users += TelegramUser.objects.filter(subscription_status=True)
        elif message.send_to_notsubscribed:
            users += TelegramUser.objects.filter(subscription_status=False)
        else:
            users += TelegramUser.objects.all()

        counter = 0
        for user in users:
            try:
                bot.send_message(chat_id=user.user_id, text=message.text, reply_markup=_markup)
                counter += 1
                message.counter = counter
                message.save(update_fields=['counter'])
            except Exception:
                pass

        message.status = 'sent'
        message.counter = counter
        message.save(update_fields=['status', 'counter'])


@shared_task
def reload_servers():
    # servers = Server.objects.filter(hosting__contains='IS Hosting')
    servers = Server.objects.filter(is_activated_vless=True)
    for server in servers:
        try:
            Logging.objects.create(category='celery', log_level='DEBUG', message=f'[CELERY] Reloading server {server.hosting}...')
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(server.ip_address, username=server.user, password=server.password)
            stdin, stdout, stderr = ssh.exec_command('sudo reboot')  # or any other command to reload the server
            ssh.close()
            Logging.objects.create(category='celery', log_level='DEBUG', message=f'[CELERY] Reloading server {server.hosting}...Done')
        except Exception as e:
            Logging.objects.create(category='celery', log_level='ERROR', message=f'[CELERY] {traceback.format_exc()}')
            pass


@shared_task
def init_marzban_servers():
    servers = Server.objects.filter(is_active=True, is_activated_vless=False).select_related('country')
    for server in servers:
        _init_marzban_single_server(server)

@shared_task
def init_celerity_servers():
    servers = Server.objects.filter(
        is_active=True,
        is_c3celeryty_activated=False,
    ).select_related('country')
    for server in servers:
        label = server.hosting or server.ip_address or f'pk={server.pk}'

        def _log(level: str, msg: str) -> None:
            Logging.objects.create(
                category='vpn',
                log_level=level,
                message=f'[CELERY] [hysteria] [{label}] {msg}',
            )

        bootstrap_celerity_for_server(
            server,
            log_fn=_log,
        )


@shared_task
def init_pasarguard_servers():
    servers = Server.objects.filter(
        is_active=True,
        is_pasarguard_activated=False,
    ).select_related("country")
    for server in servers:
        label = server.hosting or server.ip_address or f"pk={server.pk}"

        def _log(level: str, msg: str) -> None:
            Logging.objects.create(
                category="vpn",
                log_level=level,
                message=f"[CELERY] [PasarGuard] [{label}] {msg}",
            )

        bootstrap_pasarguard_for_server(server, log_fn=_log)


@shared_task
def init_all_panel_servers():
    """
    Комбинированный прогон для нового VPS: PasarGuard-node, Marzban (если enabled), Celerity.
    """
    qs = (
        Server.objects.filter(is_active=True)
        .filter(
            Q(is_pasarguard_activated=False)
            | Q(is_c3celeryty_activated=False)
            | Q(is_activated_vless=False)
        )
        .select_related("country")
    )
    for server in qs:
        label = server.hosting or server.ip_address or f"pk={server.pk}"

        def _log(panel: str, level: str, msg: str) -> None:
            Logging.objects.create(
                category="vpn",
                log_level=level,
                message=f"[CELERY] [{panel}] [{label}] {msg}",
            )

        if not server.is_pasarguard_activated:
            bootstrap_pasarguard_for_server(
                server,
                log_fn=lambda level, msg: _log("PasarGuard", level, msg),
            )

        if getattr(settings, "VPN_MARZBAN_ENABLED", True):
            provision_marzban_then_celerity(server)
        elif not server.is_c3celeryty_activated:
            bootstrap_celerity_for_server(
                server,
                log_fn=lambda level, msg: _log("hysteria", level, msg),
            )

@shared_task
def init_marzban_and_celerity_servers():
    """
    Новый VPS: сначала marzban-node (ss/vless), затем Celerity (hysteria) с pinSHA256 и SNI.
    Если ss/vless не встал, hysteria в этом прогоне не запускается.
    """
    for server in servers_pending_marzban_or_celerity():
        provision_marzban_then_celerity(server)


@shared_task
def clear_log_entry():
    try:
        log_entry = LogEntry.objects.all()
        if log_entry.exists():
            log_entry.delete()
    except Exception as e:
        pass
