import sys
import time
import traceback
import logging
from time import sleep

import paramiko

import django_orm
from bot.models import Server
from bot.models import Country

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s %(levelname) -8s %(message)s',
    level=logging.INFO,
    datefmt='%Y.%m.%d %I:%M:%S',
    handlers=[
        logging.StreamHandler(stream=sys.stderr)
              ],
)


def find_dict_item(obj, key):
    """
    Find a key in a dictionary and return its value.
    :param obj:
    :param key:
    :return:
    """
    if key in obj:
        return obj[key]
    for k, v in obj.items():
        if isinstance(v, dict):
            item = find_dict_item(v, key)
            if item is not None:
                return item


def init_servers():
    cloud_init = '#!/bin/sh\ntouch configfile.txt\nbash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh) > configfile.txt"'
    servers = Server.objects.filter(is_activated=False)
    if servers:
        for server in servers:

            # доступ по SSH и получение скрипта для outline VPN
            logger.info(f'Подключаемся к новому серверу по SSH root@{server.ip_address} pwd:{server.password} port:22')
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=server.ip_address, username=server.user, password=server.password, port=22)
                ssh.exec_command(cloud_init)
                stdin, stdout, stderr = ssh.exec_command('cat configfile.txt')
                out = stdout.read() + stderr.read()
                logger.info(f"[OUT] {out.__str__()}")
                open('configfile.txt', 'w').write(out.__str__())
                ssh.close()
            except Exception as e:
                logger.error(traceback.format_exc())
            time.sleep(1)
            logger.info('Подключение прошло успешно! Файл configfile.txt обновлён')

            # Получение apiUrl и certSha256
            logger.info('[Получение apiUrl и certSha256] [Чтение данных из configfile.txt]')
            data = dict()
            with open('configfile.txt', 'r') as config_file:
                config = config_file.read()
                for line in config.split(' '):
                    if 'interface' in line:
                        raw = line.split('{')[1].split('}')[0].split(',')
                        data['apiUrl'] = raw[0].split('":"')[-1].replace("'", "").replace('"', '')
                        data['certSha256'] = raw[1].split(':')[-1].replace("'", "").replace('"', '')

            logger.info(f'Данные их configfile.txt получены {str(data)}')
            server.script_out = data
            server.is_activated = True
            server.save()
            logger.info(f'Server обновлён успешно!')
    else:
        logger.info('Нет серверов для инициализации')


if __name__ == '__main__':
    while True:
        init_servers()
        sleep(60)