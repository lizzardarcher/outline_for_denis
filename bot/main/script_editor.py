import django_orm
from bot.models import *

servers = Server.objects.all()
keys = VpnKey.objects.all()

for server in servers:
    print(server.hosting, server.vpnkey_set.count())