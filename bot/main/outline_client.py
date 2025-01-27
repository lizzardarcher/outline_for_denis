import logging
import random
import sys
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from django.conf import settings

try:
    import django_orm
    from outline_vpn.outline_vpn import OutlineVPN
except ImportError:
    from bot.main import django_orm
    from bot.main.outline_vpn.outline_vpn import OutlineVPN
from bot.models import VpnKey, Logging
from bot.models import Server
from bot.models import TelegramUser

DEBUG = settings.DEBUG

log_path = Path(__file__).parent.absolute() / 'log/bot_log.log'
logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s %(levelname) -8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y.%m.%d %I:%M:%S',
    handlers=[
        TimedRotatingFileHandler(filename=log_path, when='D', interval=1, backupCount=5),
    ],
)


async def update_keys_data_limit(user: TelegramUser):
    try:
        data = VpnKey.objects.filter(user=user).first().server.script_out
        client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
        if DEBUG: print(data)

        #  Обновляем запись в ключе
        key_id = VpnKey.objects.filter(user=user).first().key_id
        used_bytes = client.get_transferred_data()['bytesTransferredByUserId'][key_id]
        VpnKey.objects.filter(user=user).update(used_bytes=used_bytes)
        if DEBUG: print(key_id, used_bytes)

        #  Обновляем data_limit у пользователя
        data_limit = int(user.data_limit) - int(used_bytes)
        TelegramUser.objects.filter(user_id=user.user_id).update(data_limit=data_limit)
        if DEBUG: print(data_limit)

    except:
        if DEBUG: print(traceback.format_exc())


async def create_new_key(server: Server, user: TelegramUser) -> str:
    """
    Создать новый vpn ключ
    :param server: Server from models
    :param user: TelegramUser from models
    :return: access_url
    """
    data_limit = None
    print(f"[{server}] [{user}]")
    try:
        data_limit = user.data_limit
        data_limit = data_limit
    except:
        print('no data_limit provided')
    data = dict(server.script_out)

    client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
    key = client.create_key(
        key_id=f'{str(user.user_id)}:{str(server.id)}' + f'{str(random.randint(1, 100000))}',
        name=f'{str(user.user_id)}:{server.ip_address}',
        # data_limit=data_limit
    )
    VpnKey.objects.create(
        server=server,
        user=user,
        key_id=f'{key.key_id}',
        name=key.name,
        password=key.password,
        port=key.port,
        method=key.method,
        # access_url=f'{key.access_url}',
        access_url=f'{key.access_url}#VPN',
        used_bytes=key.used_bytes,
        data_limit=key.data_limit
    )
    """
    Добавляется запись об увеличении кол-ва сгенерированных ключей на +1
    """
    try:
        # keys_generated = Server.objects.filter(id=server.id).first().keys_generated + 1
        # if DEBUG: print(keys_generated, 'keys_generated')
        # g = Server.objects.filter(id=server.id).update(keys_generated=keys_generated)
        # if DEBUG: print(g, 'g')
        keys_generated = server.keys_generated
        server.keys_generated = keys_generated + 1
        server.save()
        if DEBUG: print(keys_generated, 'keys_generated')

    except:
        logger.error(traceback.format_exc())
        print(traceback.format_exc())
    return f'{key.access_url}#{server.country.name_for_app} VPN'


async def delete_user_keys(user: TelegramUser) -> bool:
    """
    Delete all vpn-keys associated with user
    :param user: TelegramUser from models
    :return: True if deletion was successful, False otherwise
    """
    if DEBUG: print('deleting all vpn-keys for user', user.id)
    try:
        servers = [x.server.script_out for x in VpnKey.objects.filter(user=user)]
        if DEBUG: print('server data', servers)
        keys = [key.key_id for key in VpnKey.objects.filter(user=user)]
        # used_bytes = VpnKey.objects.filter(user=user).first().used_bytes
        # data_limit = int(user.data_limit) - int(used_bytes)
        # TelegramUser.objects.filter(user_id=user.user_id).update(data_limit=data_limit)
        if DEBUG: print('keys data', keys)
        for data in servers:
            client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
            for key in keys:
                try:
                    if DEBUG: print('Удаляем Ключ :: ', key)
                    client.delete_key(key)
                    keys.remove(key)
                    if DEBUG: print('Ключ Успешно Удалён :: ', key)

                    try:
                        #  Добавляется запись об уменьшении кол-ва сгенерированных ключей на -1
                        keys_generated = Server.objects.filter(script_out=data).first().keys_generated - 1
                        if DEBUG: print(keys_generated, 'keys_generated')
                        Server.objects.filter(script_out=data).update(keys_generated=keys_generated)
                    except:
                        logger.error(traceback.format_exc())

                except:
                    ...
        VpnKey.objects.filter(user=user).delete()
        Logging.objects.create(log_level='WARNING', message='[Недействительный Ключ Удалён]', datetime=datetime.now(),
                               user=user)
        return True
    except Exception as e:
        logger.error(traceback.format_exc())
        return False
