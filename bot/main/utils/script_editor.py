
from bot.main import django_orm
from bot.models import *
import datetime

# lc = Logging.objects.filter(datetime__lte=datetime.datetime.now() - datetime.timedelta(days=15)).delete()
# print(lc)
# lc = Logging.objects.filter(user__username='megafoll').delete()
# tr = Transaction.objects.filter(user__username='megafoll').delete()
# print(lc)

# vk = VpnKey.objects.filter(server__ip_address='2.56.177.127').delete()

# vk = VpnKey.objects.filter(server=None).delete()
# print(vk)