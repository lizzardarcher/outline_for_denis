from celery import shared_task

from bot.models import Logging, Transaction, IncomeInfo
from bot.models import Server

@shared_task
def create_log_entry():
    Logging.objects.create(
        log_level='DEBUG',
        message='CELERY TASKS TESTING'
    )
    return None

@shared_task
def update_generated_keys(*args, **kwargs):
    """
    Updating keys generated
    :return: None
    """
    servers = Server.objects.all()
    for server in servers:
        server.keys_generated = server.vpnkey_set.all().count()
        server.save()
    return None

@shared_task
def update_total_income(*args, **kwargs):
    """
    Updating total income
    :param args:
    :param kwargs:
    """
    transactions = Transaction.objects.filter(status='succeeded')
    income_info = IncomeInfo.objects.get(pk=1)
    total_amount = float(0)
    for transaction in transactions:
        total_amount += float(transaction.amount)
    income_info.total_amount = total_amount
    income_info.save()
    return None