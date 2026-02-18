import traceback

import paramiko
from celery import shared_task
from django.utils import timezone
from django.contrib.admin.models import LogEntry

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.main.utils import msg
from bot.main.MarzbanAPI import MarzbanAPI
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
def init_marzban_servers():
    cloud_init = """#!/bin/bash


# Set variables
CERT="-----BEGIN CERTIFICATE-----\nMIIEnDCCAoQCAQAwDQYJKoZIhvcNAQENBQAwEzERMA8GA1UEAwwIR296YXJnYWgw\nIBcNMjUwMzE3MTAxOTQyWhgPMjEyNTAyMjExMDE5NDJaMBMxETAPBgNVBAMMCEdv\nemFyZ2FoMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEApUCVwqUWeX6R\nfX+8KmTYg3E1FaY/d+oBxWa7ABTK/RjD6jrYh5jtmopbeaITuzp7Z8aobSbrVx7c\nZNHAQISJdJhZPqL+qLySFVdIh7qfBmW7WI0JRG4UBPX+vh3rOydidLPGXMdyy534\nkvUvco63XK///vC+CHAfws2lxcPj70FX702WkKNNCHH9vGiDSr2qoHWSwSObwbF/\nMuIbxNtCfKsgblZ+FcmLf/3LCEzbFGAnx6+1o7KVPvHtg5I9qWhwar2ntB2JSJ7p\nkqyFDOEecXrXKBObUAjaeIWAE3QthUaLbFTuZGcv8Jdult2z+0AeGjYv6Qcn++C5\ncE/DjUYKTibsDHlDTMebm5cGTQQF8sEeXEAXQPucV18HWcvtmdl4WeXWmlO9osDs\nN1kvpt6ECC8/ihb5kLUrVKaoPkmUCSKqAaxfVrLHIr64So9ZgmvmZv1LcZDp7ji0\nS24PlG3ztfg6RnynteYey6+HOm5KJBtKL6ALsj87ZiYdVzca9WNVKXfzF0I1DbY4\nIDngKjvoeftjzGD64cNM1HvHUeR8uqhpiLeLHrEahPx7mXpVqcvx7+WSYrzbde4l\ni9yCrDRHzoQAi5kDi+hdiuItQIzbVh54AtVnmF8XLliu8vwEdSBJgJ2Jy9TBjVA7\n8ijRyNpT+8c67XqHBVA/9ZXpolSx3GcCAwEAATANBgkqhkiG9w0BAQ0FAAOCAgEA\nNdXGyIPmoxWwGXPF1b6jp8wxdf94fdydVDFea2sJIb4iXRD8GEl2aJAXG75xmn5c\nrHerGG7iEXWF2FImkze8+zYHI31HP6nhZvKqT08OUVxf/6+0zmEo/RUxngzyPI1F\nSRi+ao53VGwWoIdcd/KjDty1I2CXccB7xfh/jOJdmLPopPQZLXMq2FLJ/efE21IP\n4YwmCVNwUuuyRs8V3RiKlPlWrrdSuvdDjKlu3sEGuVzy9YE7mAg7eY7vlYpB3XiM\ncIi6R4a0pZd5sdKFFH5mdhp0xKrLqlO+5fjCOzVTVkDOZSeVaedNuTfcScJvVmUJ\nF/yrOvKzFJw+uYltNob7iPgt4H8uVidhsrxTS/WMLK/4gbMyYV/sTPqklPNLqzF2\nKV3GJDht6nqKbCkCnZUS0ZN6F0CwTUw3xvEli3KSVJ2fkh9yaNlrvkqv7AMTrB8b\n/Qxo0tNL1p0u8UKRfARXRpMCs9zE+PPm5NjnKg2Y9+lbf6ZPrmcTMESHVbL2cdAf\n/oP+3mTDkXaexLdIaqGhn95m88rqO38fNTc6odGIBGC1v93zrAEFqB+MLTryPSwK\n7eBBQvWaV4fMI88FLOv8TqVmRDZNI972CHU0tvFaLTZ21V3a1zKT/cKyOs44Y8ui\ncCWzgxcswewONXi6yhxefFx14Z2jx9eoa4kbwJvHteU=\n-----END CERTIFICATE-----\n"
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

apt-get install git -y
apt-get install socat -y
apt-get install docker.io -y
apt-get install docker-compose -y

git clone https://github.com/Gozargah/Marzban-node

mkdir -p /var/lib/marzban-node/

echo "$CERT" > /var/lib/marzban-node/ssl_client_cert.pem

cd Marzban-node && rm -f docker-compose.yml && echo "$DOCKER_COMPOSE_YML" > docker-compose.yml && docker compose down  && docker compose up -d

echo "Script completed successfully."
    """
    servers = Server.objects.filter(is_active=True, is_activated_vless=False)
    # servers = Server.objects.filter(ip_address='103.106.3.58')
    if servers:
        for server in servers:
            Logging.objects.create(log_level='DEBUG', message=f'Initializing server {server.hosting}...')
            try:
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh_client.connect(hostname=server.ip_address, username=server.user, password=server.password)
                stdin, stdout, stderr = ssh_client.exec_command(cloud_init)
                stdout_output = stdout.read().decode('utf-8')
                stderr_output = stderr.read().decode('utf-8')
                return_code = stdout.channel.recv_exit_status()
                ssh_client.close()

                try:
                    marzban = MarzbanAPI()
                    new_node = marzban.add_node(ip=server.ip_address,
                                                name=f'{server.country.name_for_app} {server.hosting}')
                    if 'True' not in str(new_node):
                        ...
                    else:
                        server.is_activated_vless = True
                        server.save()
                        Logging.objects.create(log_level='INFO', message=f'Initializing server {server.hosting}...Done')
                except:
                    Logging.objects.create(log_level='DEBUG', message=f'Initializing server {server.hosting}...Failed')
                    print(traceback.format_exc())

            except paramiko.AuthenticationException:
                Logging.objects.create(log_level='ERROR', message=f'Initializing server {server.hosting}...Failed')
                print("Ошибка аутентификации. Неверное имя пользователя или пароль.")
                return None
            except paramiko.SSHException as e:
                Logging.objects.create(log_level='ERROR', message=f'Initializing server {server.hosting}...Failed')
                print(f"Ошибка SSH: {e}")
                return None
            except Exception as e:
                Logging.objects.create(log_level='ERROR', message=f'Initializing server {server.hosting}...Failed')
                print(f"Произошла ошибка: {e}")
                return None
    else:
        ...


@shared_task
def clear_log_entry():
    try:
        log_entry = LogEntry.objects.all()
        if log_entry.exists():
            log_entry.delete()
    except Exception as e:
        pass
