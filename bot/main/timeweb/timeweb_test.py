import os
import time

import requests
from bot.main.timeweb.timeweb import TimeWeb

token = 'eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCIsImtpZCI6IjFrYnhacFJNQGJSI0tSbE1xS1lqIn0.eyJ1c2VyIjoiY3E0NzU5NiIsInR5cGUiOiJhcGlfa2V5IiwicG9ydGFsX3Rva2VuIjoiNjM5MGRjZjAtZjJhYy00MDY1LTk4OWEtMjdiZjQzZjUyZTAyIiwiYXBpX2tleV9pZCI6ImEzM2YyOWQwLTM2ZDEtNDgxYy05NDIyLTgzNGYzYjBjODVkZCIsImlhdCI6MTcxMjU0MzExN30.y4bqGsLX8CuHEMHas-ZPa7Z-pk2aD-o6Nt-ci-D3Qj7H336SkZLcmSL0ybLoJo_yysXAt6Lsyf8ToLF-5oH81dF8eozASaMR2EF__T3D5rB21NjLAByKmAuHYxeXx5eJ-Glor19c4uiQijqOYt_gzT8Uo3LoDLFNQFc63FUUzhktmtzmE7KA30QBnud0lM0xkjnT-j9ZAKIMuCa-oT0PAMo61wzFd72k7wPqKYiE9h390LKSyYeJV1WyCDbPITd5JV-aGUsjNMtPov8ZwxyZpX8aCcIeL1_l7yrtQYrS7sxKzH-HgIvnBLBWt3oUsQGojKfstzLCDE5cHDebggn8NOpHZzdDCpy5A3DwVpH5rJ477vpRK3NVYO9SmEHYhm-xnKcdgGbKle1WnFA-_q_Oguye8oeoG-byvOt0n_C7Hyx4ie3R-_BUI0mp5osEZ9xy8diV4xbqyy9wjgW578gT0u4tR8Af32ww9tmfZokvr_H40ynrP-6DIO5EuVHKLQ0E'
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}',
}

cloud_init = '#!/bin/sh\ntouch configfile.txt\nbash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh) > configfile.txt"'
js = {'server': {'id': 2814653, 'name': 'outline_ru_1', 'comment': 'comment',
                 'os': {'id': 79, 'name': 'ubuntu', 'version': '22.04'}, 'software': {'id': 25, 'name': 'Docker'},
                 'preset_id': 2447, 'configurator_id': None, 'location': 'ru-1', 'availability_zone': 'spb-2',
                 'boot_mode': 'std', 'status': 'installing', 'start_at': None, 'is_ddos_guard': False,
                 'is_master_ssh': False, 'avatar_id': None, 'vnc_pass': '', 'cpu': 1, 'cpu_frequency': '3.3',
                 'ram': 1024, 'created_at': '2024-04-08T02:31:34.000Z', 'networks': [
        {'type': 'public', 'bandwidth': 200,
         'ips': [{'ip': '2a03:6f00:5:1::6073', 'is_main': True, 'ptr': '2814653-cq47596.twc1.net', 'type': 'ipv6'},
                 {'ip': '85.193.90.139', 'is_main': True, 'ptr': '2814653-cq47596.twc1.net', 'type': 'ipv4'}],
         'blocked_ports': []}], 'disks': [
        {'size': 15360, 'used': 0, 'id': 18078477, 'type': 'nvme', 'is_mounted': True, 'is_system': True,
         'status': 'done', 'system_name': 'vda', 'is_auto_backup': False}], 'image': None, 'root_pass': None,
                 'cloud_init': '#!/bin/sh\nsudo bash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh > var/www/output.txt)"\n',
                 'is_qemu_agent': True}, 'response_id': '3b8f4625-78d2-4d8f-8277-8e72a6bfd4fd'}

sv = {'server': {'id': 2814653, 'name': 'outline_ru_1', 'comment': 'comment',
                 'os': {'id': 79, 'name': 'ubuntu', 'version': '22.04'}, 'software': {'id': 25, 'name': 'Docker'},
                 'preset_id': 2447, 'configurator_id': None, 'location': 'ru-1', 'availability_zone': 'spb-2',
                 'boot_mode': 'std', 'status': 'on', 'start_at': '2024-04-08T05:32:04.000Z', 'is_ddos_guard': False,
                 'is_master_ssh': False, 'avatar_id': None, 'vnc_pass': 'v-7WZivTRm-deS', 'cpu': 1,
                 'cpu_frequency': '3.3', 'ram': 1024, 'created_at': '2024-04-08T02:31:34.000Z', 'networks': [
        {'type': 'public', 'bandwidth': 200,
         'ips': [{'ip': '2a03:6f00:5:1::6073', 'is_main': True, 'ptr': '2814653-cq47596.twc1.net', 'type': 'ipv6'},
                 {'ip': '85.193.90.139', 'is_main': True, 'ptr': '2814653-cq47596.twc1.net', 'type': 'ipv4'}],
         'blocked_ports': []}], 'disks': [
        {'size': 15360, 'used': 0, 'id': 18078477, 'type': 'nvme', 'is_mounted': True, 'is_system': True,
         'status': 'done', 'system_name': 'vda', 'is_auto_backup': False}], 'image': None,
                 'root_pass': 'bN3+TNQ9^H5YXq',
                 'cloud_init': '#!/bin/sh\nsudo bash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh > var/www/output.txt)"\n',
                 'is_qemu_agent': True}, 'response_id': 'c093adc3-db9e-4123-9d75-2f7f3f1c54e9'}

json_data = {  # for creating servers
    'is_ddos_guard': False,
    'os_id': 79,  # Ubuntu 22.04
    'software_id': 25,  # Docker
    'bandwidth': 200,
    'comment': 'comment',
    'name': 'outline_ru_1',
    'cloud_init': cloud_init,
    'preset_id': 2447,
    'is_local_network': False,
}

# 3344 netherland
# 2551 poland
# 3795 kazakstan

client = TimeWeb(token=token, headers=headers)

server = client.create_server(json_data=json_data)
print(server)

time.sleep(300)

server_id = server['server']['id']
ip = server['server']['networks'][0]['ips'][1]['ip']
password = server['server']['root_pass']

server = client.get_server(server_id=server_id)
print(server)

# finances = client.get_finances()
# print(finances)

# servers = client.get_servers()
# print(servers)

# servers_os = client.get_servers_os()
# print(servers_os['servers_os'])
# for i in servers_os['servers_os']:
#     print(i)


# info = client.get_servers_software()
# print(info['servers_software'])
#
# for i in info['servers_software']:
#     print(i)
