from django.db.models.signals import pre_delete
from django.dispatch import receiver

from bot.models import Server

@receiver(pre_delete, sender=Server)
def cleanup_server_panels_on_delete(sender, instance, **kwargs):
    from bot.main.server_panel_cleanup import delete_server_from_panels

    delete_server_from_panels(instance)
