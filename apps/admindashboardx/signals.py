
from django.db.models.signals import post_delete, post_save

from bot.models import TelegramUser, Transaction

from .cache_utils import bust_admx_dashboard_caches


def _invalidate_on_tx_change(sender, **kwargs):
    bust_admx_dashboard_caches()


def _invalidate_on_user_change(sender, **kwargs):
    bust_admx_dashboard_caches()


post_save.connect(_invalidate_on_tx_change, sender=Transaction)
post_delete.connect(_invalidate_on_tx_change, sender=Transaction)
post_save.connect(_invalidate_on_user_change, sender=TelegramUser)
