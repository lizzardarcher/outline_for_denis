from celery import shared_task

from bot.models import Logging
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
        # Logging.objects.create(log_level='DEBUG', message='Updating keys generated SUCCESS#####!')
    return None
