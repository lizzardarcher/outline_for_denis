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
    try:
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
            # access_url=f'{key.access_url}',
            access_url=f'{key.access_url}#VPN',
            used_bytes=key.used_bytes,
            data_limit=key.data_limit
        )
        return f'{key.access_url}#{server.country.name_for_app} VPN'
    except:
        Logging.objects.create(text=f'User {user.user_id} has failed to create a key on {server.ip_address} server')
        print(traceback.format_exc())





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
                except:
                    ...
        VpnKey.objects.filter(user=user).delete()
        Logging.objects.create(log_level='WARNING', message='[BOT] [Недействительный Ключ Удалён]', datetime=datetime.now(),
                               user=user)
        return True
    except Exception as e:
        logger.error(traceback.format_exc())
        return False
