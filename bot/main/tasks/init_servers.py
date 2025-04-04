import time
import traceback
from time import sleep
import paramiko
import django_orm
from bot.main.vless.MarzbanAPI import MarzbanAPI
from bot.models import Server


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


def init_outline_servers():
    cloud_init = '#!/bin/sh\ntouch configfile.txt\nbash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh) > configfile.txt"'
    servers = Server.objects.filter(is_active=True, is_activated=False)
    if servers:
        for server in servers:

            # доступ по SSH и получение скрипта для outline VPN
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=server.ip_address, username=server.user, password=server.password, port=22)
                ssh.exec_command(cloud_init)
                stdin, stdout, stderr = ssh.exec_command('cat configfile.txt')
                out = stdout.read() + stderr.read()
                open('configfile.txt', 'w').write(out.__str__())
                ssh.close()
            except Exception as e:
                ...
            time.sleep(1)

            # Получение apiUrl и certSha256
            data = dict()
            with open('configfile.txt', 'r') as config_file:
                config = config_file.read()
                for line in config.split(' '):
                    if 'interface' in line:
                        raw = line.split('{')[1].split('}')[0].split(',')
                        data['apiUrl'] = raw[0].split('":"')[-1].replace("'", "").replace('"', '')
                        data['certSha256'] = raw[1].split(':')[-1].replace("'", "").replace('"', '')

            server.script_out = data
            server.is_activated = True
            server.save()
    else:
        ...


def init_vless_servers():
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

cd Marzban-node && rm -f docker-compose.yml && echo "$DOCKER_COMPOSE_YML" > docker-compose.yml && docker-compose down  && docker-compose up -d

echo "Script completed successfully."
    """
    servers = Server.objects.filter(is_active=True, is_activated_vless=False)
    # servers = Server.objects.filter(ip_address='103.106.3.58')
    if servers:
        for server in servers:
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
                    new_node = marzban.add_node(ip=server.ip_address, name=f'{server.country.name_for_app} {server.hosting}')
                    if 'True' not in str(new_node):
                        ...
                    else:
                        server.is_activated_vless = True
                        server.save()
                except:
                    print(traceback.format_exc())

            except paramiko.AuthenticationException:
                print("Ошибка аутентификации. Неверное имя пользователя или пароль.")
                return None
            except paramiko.SSHException as e:
                print(f"Ошибка SSH: {e}")
                return None
            except Exception as e:
                print(f"Произошла ошибка: {e}")
                return None
    else:
        ...

if __name__ == '__main__':

    while True:
        init_outline_servers()
        init_vless_servers()
        sleep(60)

