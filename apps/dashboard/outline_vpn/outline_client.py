import random
import traceback
from datetime import datetime

from django.conf import settings

import apps.dashboard.outline_vpn.django_orm
from apps.dashboard.outline_vpn.outline_vpn import OutlineVPN
from bot.models import VpnKey
from bot.models import Server
from bot.models import Logging
from bot.models import TelegramUser

DEBUG = settings.DEBUG


def create_new_key(server: Server, user: TelegramUser) -> str:
    data = dict(server.script_out)
    client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
    key = client.create_key(
        key_id=f'{str(user.user_id)}:{str(server.id)}' + f'{str(random.randint(1, 100000))}',
        name=f'{str(user.user_id)}:{server.ip_address}',
    )
    VpnKey.objects.create(
        server=server,
        user=user,
        key_id=f'{key.key_id}',
        name=key.name,
        password=key.password,
        port=key.port,
        method=key.method,
        access_url=f'{key.access_url}#VPN',
        used_bytes=key.used_bytes,
        data_limit=key.data_limit
    )
    keys_generated = server.keys_generated
    server.keys_generated = keys_generated + 1
    server.save()
    Logging.objects.create(log_level='INFO', message=f'[WEB] [Новый Ключ Создан]', datetime=datetime.now(), user=user)
    return f'{key.access_url}#{server.country.name_for_app} VPN'


def delete_user_keys(user: TelegramUser):
    servers = [x.server.script_out for x in VpnKey.objects.filter(user=user)]
    keys = [key.key_id for key in VpnKey.objects.filter(user=user)]
    for data in servers:
        client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
        for key in keys:
            try:
                client.delete_key(key)
                keys.remove(key)
                Logging.objects.create(log_level='WARNING', message='[WEB] [Недействительный Ключ Удалён]',
                                       datetime=datetime.now(), user=user)
                try:
                    #  Добавляется запись об уменьшении кол-ва сгенерированных ключей на 1
                    keys_generated = Server.objects.filter(script_out=data).first().keys_generated - 1
                    Server.objects.filter(script_out=data).update(keys_generated=keys_generated)
                except:
                    Logging.objects.create(log_level='ERROR', message=f'{traceback.format_exc()}',
                                           datetime=datetime.now(), user=user)
            except:
                Logging.objects.create(log_level='ERROR', message=f'{traceback.format_exc()}', datetime=datetime.now(),
                                       user=user)

    VpnKey.objects.filter(user=user).delete()
