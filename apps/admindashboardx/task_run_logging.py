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


class ConsoleTaskRunLogger(TaskRunLogger):
    """Логирует в bot.Logging и дублирует вывод в консоль."""

    def __init__(self, *, channel="BOT", stdout=None, style=None):
        super().__init__(run_id=None, channel=channel)
        self.stdout = stdout
        self.style = style

    def log(self, level, message, user=None):
        super().log(level, message, user=user)
        if not self.stdout:
            return
        line = f"[{level}] {message}"
        if self.style:
            if level == "SUCCESS":
                line = self.style.SUCCESS(line)
            elif level in ("WARNING", "FATAL"):
                line = self.style.ERROR(line)
            elif level == "DEBUG":
                line = self.style.NOTICE(line)
        self.stdout.write(line)
