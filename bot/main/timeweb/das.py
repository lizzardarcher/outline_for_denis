import sys
import time

server = {'server': {'id': 2814653, 'name': 'outline_ru_1', 'comment': 'comment',
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
server_id = server['server']['id']
# ip = server['server']['networks'][0]['ips'][1]['ip']
# password = server['server']['root_pass']

# print(server_id,ip, password)
#
#
# from datetime import date
# d = date.today().__str__()
# print(d, type(d))


ss = {'server': {'id': 2816669, 'name': 'netherland-3344-2024-04-08', 'comment': 'comment', 'os': {'id': 79, 'name': 'ubuntu', 'version': '22.04'}, 'software': {'id': 25, 'name': 'Docker'}, 'preset_id': 3344, 'configurator_id': None, 'location': 'nl-1', 'availability_zone': 'ams-1', 'boot_mode': 'std', 'status': 'on', 'start_at': '2024-04-08T11:33:00.000Z', 'is_ddos_guard': False, 'is_master_ssh': False, 'avatar_id': None, 'vnc_pass': 'iQ*rZ5ELT2,r*-', 'cpu': 2, 'cpu_frequency': '3.3', 'ram': 2048, 'created_at': '2024-04-08T08:30:52.000Z', 'networks': [{'type': 'public', 'bandwidth': 200, 'ips': [{'ip': '81.31.245.183', 'is_main': True, 'ptr': '2816669-cq47596.twc1.net', 'type': 'ipv4'}], 'blocked_ports': []}], 'disks': [{'size': 40960, 'used': 0, 'id': 18080579, 'type': 'nvme', 'is_mounted': True, 'is_system': True, 'status': 'done', 'system_name': 'vda', 'is_auto_backup': False}], 'image': None, 'root_pass': 'rKPSkxEr,7iG?G', 'cloud_init': '#!/bin/sh\r\ntouch configfile.txt\r\nbash -c "$(wget -qO- https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh) > configfile.txt', 'is_qemu_agent': True}, 'response_id': 'ab4662a0-5109-4c09-831f-761a4e0c5e65'}


ip = ss['server']['networks'][0]['ips'][0]['ip']
password = ss['server']['root_pass']

print(ip, password)

def timer(seconds: int):
    print(f'Starting {seconds} seconds')
    counter = 1
    while counter <= seconds:
        print("Loading" + "." * counter)
        sys.stdout.write("\033[F")  # Cursor up one line
        time.sleep(1)

for x in range (0,5):
    b = "Loading" + "." * x
    print (b, end="\r")
    time.sleep(1)