import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_for_denis.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()
from django.db.models import Sum
from bot.models import Transaction, TelegramUser


def calculate_total_amount():
    total = Transaction.objects.aggregate(total_amount=Sum('amount'))
    return total['total_amount'] or 0

def calculate_total_amount_by_user(_user):
    total = Transaction.objects.filter(user=_user).aggregate(total_amount=Sum('amount'))
    return total['total_amount'] or 0



if __name__ == "__main__":
    user_id = 5566146968
    user = TelegramUser.objects.get(user_id=user_id)
    user_amount = calculate_total_amount_by_user(user)
    total_amount = calculate_total_amount()
    print(total_amount - user_amount)