import django_orm
from bot.models import *

servers = Server.objects.all()
for server in servers:
    server.keys_generated = server.vpnkey_set.all().count()
    server.save()
