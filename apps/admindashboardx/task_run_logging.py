from datetime import datetime

from bot.models import Logging

from .models import ManualTaskLog



class TaskRunLogger:
    """Пишет в ManualTaskLog при ручном запуске, иначе — в bot.models.Logging."""

    def __init__(self, run_id=None, channel="BOT"):
        self.run_id = run_id
        self.channel = channel

    def log(self, level, message, user=None):
        if self.run_id:
            ManualTaskLog.objects.create(
                run_id=self.run_id,
                log_level=level,
                message=message,
            )
        else:
            Logging.objects.create(
                category="payment",
                log_level=level,
                message=message,
                datetime=datetime.now(),
                user=user,
            )
