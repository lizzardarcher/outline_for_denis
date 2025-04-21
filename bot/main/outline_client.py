import random
import traceback
from datetime import datetime

try:
    import django_orm
    from outline_vpn.outline_vpn import OutlineVPN
except ImportError:
    from bot.main import django_orm
    from bot.main.outline_vpn.outline_vpn import OutlineVPN
from bot.models import VpnKey, Logging
from bot.models import Server
from bot.models import TelegramUser


async def create_new_key(server: Server, user: TelegramUser) -> str:
    """
    Создать новый vpn ключ
    :param server: Server from models
    :param user: TelegramUser from models
    :return: access_url
    """
    data = dict(server.script_out)
    Logging.objects.create(log_level='DEBUG', message=f'[Ключ создаётся {data}]', datetime=datetime.now(), user=user)
    try:
        client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
        Logging.objects.create(log_level='DEBUG', message=f'[Client] {client}', datetime=datetime.now(), user=user)

        key = client.create_key(
            key_id=f'{str(user.user_id)}:{str(server.id)}' + f'{str(random.randint(1, 100000))}',
            name=f'{str(user.user_id)}:{server.ip_address}',
        )

        Logging.objects.create(log_level='DEBUG', message=f'[Key] {key}', datetime=datetime.now(), user=user)

        vk = VpnKey.objects.create(
            server=server,
            user=user,
            key_id=f'{key.key_id}',
            name=key.name,
            password=key.password,
            port=key.port,
            method=key.method,
            access_url=f'{key.access_url}#VPN',
            used_bytes=key.used_bytes,
        )

        Logging.objects.create(log_level='DEBUG', message=f'[Ключ Создан] {vk}', datetime=datetime.now(), user=user)
        return f'{key.access_url}#{server.country.name_for_app} VPN'
    except:
        Logging.objects.create(text=f'User {user.user_id} has failed to create a key on {server.ip_address} server')


async def delete_user_keys(user: TelegramUser) -> bool:
    """
    Delete all vpn-keys associated with user
    :param user: TelegramUser from models
    :return: True if deletion was successful, False otherwise
    """
    try:
        servers = [x.server.script_out for x in VpnKey.objects.filter(user=user)]
        keys = [key.key_id for key in VpnKey.objects.filter(user=user)]

        for data in servers:
            client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
            for key in keys:
                try:
                    client.delete_key(key)
                    keys.remove(key)
                except:
                    ...
        VpnKey.objects.filter(user=user).delete()
        Logging.objects.create(log_level='WARNING', message='[BOT] [Недействительный Ключ Удалён]', datetime=datetime.now(),
                               user=user)
        return True
    except Exception as e:
        return False


def sync_delete_user_keys(user: TelegramUser) -> bool:
    """
    Delete all vpn-keys associated with user
    :param user: TelegramUser from models
    :return: True if deletion was successful, False otherwise
    """
    try:
        servers = [x.server.script_out for x in VpnKey.objects.filter(user=user)]
        keys = [key.key_id for key in VpnKey.objects.filter(user=user)]

        for data in servers:
            client = OutlineVPN(api_url=data['apiUrl'], cert_sha256=data['certSha256'])
            for key in keys:
                try:
                    client.delete_key(key)
                    keys.remove(key)
                except:
                    ...
        VpnKey.objects.filter(user=user).delete()
        Logging.objects.create(log_level='WARNING', message='[BOT] [Недействительный Ключ Удалён]', datetime=datetime.now(),
                               user=user)
        return True
    except Exception as e:
        return False