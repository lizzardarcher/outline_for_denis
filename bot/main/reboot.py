import os
import time
import traceback
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_for_denis.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

import paramiko

from bot.models import Server


servers = Server.objects.filter(hosting__contains='IS Hosting')
for server in servers:
    try:
        print(f'[CELERY] Reloading server {server.hosting}...')
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server.ip_address, username=server.user, password=server.password)
        stdin, stdout, stderr = ssh.exec_command('sudo reboot')  # or any other command to reload the server
        ssh.close()
        print(f'[CELERY] Reloading server {server.hosting}...Done')
        time.sleep(3)
    except Exception as e:
        print(traceback.format_exc())
        time.sleep(3)
        pass