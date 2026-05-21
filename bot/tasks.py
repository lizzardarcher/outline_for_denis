import traceback

import paramiko
from celery import shared_task
from django.db.models import Q
from django.utils import timezone
from django.contrib.admin.models import LogEntry

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from apps.mtproxy.tasks import revoke_mtproxy_keys_for_user_task
from bot.main.celerity_key_issue import try_delete_celerity_user
from bot.main.utils import msg
from bot.main.MarzbanAPI import MarzbanAPI
from bot.main.celerity_node_bootstrap import bootstrap_celerity_for_server
from bot.models import Logging, Transaction, IncomeInfo, TelegramUser, TelegramBot, VpnKey, TelegramMessage
from bot.models import Server


CLOUD_INIT_MARZBAN = r"""#!/bin/bash


# Set variables
CERT="-----BEGIN CERTIFICATE-----\nMIIEnDCCAoQCAQAwDQYJKoZIhvcNAQENBQAwEzERMA8GA1UEAwwIR296YXJnYWgw\nIBcNMjYwNTE5MDg1NTE0WhgPMjEyNjA0MjUwODU1MTRaMBMxETAPBgNVBAMMCEdv\nemFyZ2FoMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEArflKFFIAufDf\nk3+HqTlteUwiBaJpalvsX0WwUHsXL/hUD+FVhosAUV6CU+v7jmMDr8i4YmsobCAC\neNlR28fCBZikYkVhiJEHhxzd5uQQDZ/AsKYTnvvHYPncGIIU8D0G/ll3iqgYOtmM\nJdj+YG5a28VbQMsTmK3zcYZTLg9Qo939YIzlPIhWQ3endHOX2FfBlfEuH2+hIyI+\no8QwUrcVPD4LEqM/9wIS1pzo21xEDU9MzjCJ6A1ooyp/SfAkX2Smsf28lE6o9ZWn\nAxpP6gn1eArI1ck58jj5YfgV2FYZ9DQjn45BtbACxcI7QRTTu3rLiwLFjRZ9f9AN\noJaAltUf5EaeI43wBqeAPcixQzS5RADZPVA4cvLm1Yd0IrHyekNQYDJY2FhajTeq\nRSnZ0xoZ92snmOBhaxdGSLthOw4hm3T3RSvGEdpJrMRv+xZtzk5JKyyyr44sqgQ9\nh6AaJ3c9AojJyX8meuHabi6lea6zwRIs8/wQBuUqeif/+seWKDXa2BB5garI5GYr\n6RxgTPFrkcm10KZrTlr4bJ/hhUI1Ya1eA4IjxH1fAfixDlI7AczrkpyDfaYggBnc\nzOwQYVT/mAAXEtE/p35C/dVJqB18eP//LT1GiEKniIO9UoQwy17XLJWSSAzESeSK\nYWQ/rn8RBK7X/gdYNib1OZn5TfqT8OsCAwEAATANBgkqhkiG9w0BAQ0FAAOCAgEA\nhKn5aO/hCz5RtvQfiDMx9Rq/a/VcuPVZv8CREXinceVKZalCtD7pkE9Y2spHxb0E\nJU6HLfGNabblJbAdW0r205ejShHm5yOKIfzO7p6Qwfwd+XFLdPoKK5jUEr5qwG74\nvyLjfzUiS0cIbvc7x5Sb3aR7HyEV2XHDiTrXi0fA43ntQXIZ9nU9hk3MVVLm3R6j\nOvPsrirE3Sm0C0GbxSg7YAE+XfqHuxc4fZUkAhmCFVdE+8734uYdRx4f9iHxvuRN\n+n1hO2/7ulDK4VJ31om9p7pbTdp56an6VxxHRg18nEWriGGbVRlF+F+OjTWeBsj1\nFXgXPrZPq+mkNIf3p3PKNZfwoKKRdAD/9kq0cJn7w3rb2AP14x+z9qYBX3TzGaCf\nz+Eb4MWweD/pyZ8SbUwNRZsLGtpbyFQN3Y76r/YOA4+lX8N0mr9indnNg8XQfFCW\nJ6TTcxwiIy+NK8XVGSoKVvXd1lqFFL78gG0jYtwLFy0IV5L4goe9fFBqXTsNaPR+\nj/zpFFE2Wjosp0ozlFMScOeuPambFvVWO80F/MuQumg7YIu3VK8m/wAbWiwIENM+\nJO/xsMuIlDhFezZ6jwAebAHWX5pmdAk/9hraniiCQUiRwGIwYhNP4if0jYgG7YzK\n0e4u1GLX14U000cBXY3truvC0PkPqD0E1/nxWwwBlM0=\n-----END CERTIFICATE-----\n"
DOCKER_COMPOSE_YML="services:
  marzban-node:
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host

    volumes:
      - /var/lib/marzban-node:/var/lib/marzban-node

    environment:
      SSL_CLIENT_CERT_FILE: /var/lib/marzban-node/ssl_client_cert.pem
      SERVICE_PROTOCOL: rest"
apt update
apt install git -y
apt install socat -y
apt install docker.io -y
apt install docker-compose -y

git clone https://github.com/Gozargah/Marzban-node

mkdir -p /var/lib/marzban-node/

echo "$CERT" > /var/lib/marzban-node/ssl_client_cert.pem

cd Marzban-node && rm -f docker-compose.yml && echo "$DOCKER_COMPOSE_YML" > docker-compose.yml && docker-compose down  && docker-compose up -d

echo "Script completed successfully."
"""


def _init_marzban_single_server(server: Server, cloud_init: str) -> bool:
    """
    SSH cloud-init marzban-node + регистрация ноды в Marzban. При успехе — is_activated_vless=True.
    """
    Logging.objects.create(
        category='vpn',
        log_level='DEBUG',
        message=f'[CELERY] [Marzban] Инициализация сервера {server.hosting}...',
    )
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname=server.ip_address, username=server.user, password=server.password)
        stdin, stdout, stderr = ssh_client.exec_command(cloud_init)
        stdout.read()
        stderr.read()
        stdout.channel.recv_exit_status()
        ssh_client.close()

        try:
            marzban = MarzbanAPI()
            new_node = marzban.add_node(
                ip=server.ip_address,
                name=f'{server.country.name_for_app} {server.hosting}',
            )
            if 'True' not in str(new_node):
                Logging.objects.create(
                    category='vpn',
                    log_level='DEBUG',
                    message=f'[CELERY] [Marzban] add_node не подтвердился: {server.hosting}',
                )
                return False
            server.is_activated_vless = True
            server.save()
            Logging.objects.create(
                category='vpn',
                log_level='INFO',
                message=f'[CELERY] [Marzban] Готово: {server.hosting}',
            )
            return True
        except Exception:
            Logging.objects.create(
                category='vpn',
                log_level='DEBUG',
                message=f'[CELERY] [Marzban] Ошибка после SSH (add_node): {server.hosting}\n{traceback.format_exc()}',
            )
            return False

    except paramiko.AuthenticationException:
        Logging.objects.create(
            category='vpn',
            log_level='ERROR',
            message=f'[CELERY] [Marzban] SSH аутентификация: {server.hosting}',
        )
        return False
    except paramiko.SSHException as e:
        Logging.objects.create(
            category='vpn',
            log_level='ERROR',
            message=f'[CELERY] [Marzban] SSH: {server.hosting}: {e}',
        )
        return False
    except Exception as e:
        Logging.objects.create(
            category='vpn',
            log_level='ERROR',
            message=f'[CELERY] [Marzban] {server.hosting}: {e}\n{traceback.format_exc()}',
        )
        return False


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

    users = TelegramUser.objects.filter(subscription_expiration__lt=timezone.now(), subscription_status=True)
    for user in users:
        try:
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

    vpn_keys = VpnKey.objects.filter(user__subscription_status=False)
    for key in vpn_keys:
        try:
            MarzbanAPI().delete_user(username=str(key.user.user_id))
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
        _init_marzban_single_server(server, CLOUD_INIT_MARZBAN)

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
                message=f'[CELERY] [Celerity] [{label}] {msg}',
            )

        bootstrap_celerity_for_server(
            server,
            log_fn=_log,
        )


@shared_task
def init_marzban_and_celerity_servers():
    """
    Комбинированный прогон для нового VPS: Marzban-node, затем нода Celerity.

    Порядок осознанный: сначала ставим docker marzban-node по SSH и регистрируем
    ноду в панели Marzban; затем (если ещё не отмечено) создаём/находим ноду в
    Celerity и вызываем setup (установка ПО на той же машине по SSH из API).
    """
    # Только активные записи, где не хватает хотя бы одного из двух этапов.
    qs = (
        Server.objects.filter(is_active=True)
        .filter(Q(is_activated_vless=False) | Q(is_c3celeryty_activated=False))
        .select_related('country')
    )
    for server in qs:
        # Этап 1: VLESS/Marzban — пропускаем, если уже успешно прошли ранее.
        if not server.is_activated_vless:
            _init_marzban_single_server(server, CLOUD_INIT_MARZBAN)
            # Объект в памяти мог устареть после save() внутри helper'а — подтянуть флаги из БД.
            server.refresh_from_db(
                fields=['is_activated_vless', 'is_c3celeryty_activated'],
            )

        # Этап 2: Celerity не нужен, если ключ is_c3celeryty_activated уже True
        # (например Marzban только что не прошёл, но Celerity раньше уже накатывали).
        if server.is_c3celeryty_activated:
            continue

        label = server.hosting or server.ip_address or f'pk={server.pk}'

        def _log(level: str, msg: str) -> None:
            Logging.objects.create(
                category='vpn',
                log_level=level,
                message=f'[CELERY] [Marzban+Celerity] [{label}] {msg}',
            )

        # POST /nodes при необходимости + setup; при успехе ставит is_c3celeryty_activated=True.
        bootstrap_celerity_for_server(
            server,
            log_fn=_log,
        )


@shared_task
def clear_log_entry():
    try:
        log_entry = LogEntry.objects.all()
        if log_entry.exists():
            log_entry.delete()
    except Exception as e:
        pass
