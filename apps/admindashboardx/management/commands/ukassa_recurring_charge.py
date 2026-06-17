"""
Рекуррентное списание YooKassa (bot / site) из консоли, без Celery.


Примеры:
  python manage.py ukassa_recurring_charge --dry-run
  python manage.py ukassa_recurring_charge --bot-only --dry-run
  python manage.py ukassa_recurring_charge --site-only --dry-run
  python manage.py ukassa_recurring_charge --bot-only --no-input
  python manage.py ukassa_recurring_charge --no-input
"""
from django.core.management.base import BaseCommand, CommandError

from apps.admindashboardx.task_run_logging import ConsoleTaskRunLogger
from apps.admindashboardx.ukassa_recurring import (
    run_ukassa_bot_recurring,
    run_ukassa_site_recurring,
)


class Command(BaseCommand):
    help = "Рекуррентное списание YooKassa Bot/Site из консоли (без Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать план списаний без запросов в YooKassa и без изменений в БД.",
        )
        parser.add_argument(
            "--bot-only",
            action="store_true",
            help="Только YooKassa Bot.",
        )
        parser.add_argument(
            "--site-only",
            action="store_true",
            help="Только YooKassa Site.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Не спрашивать подтверждение (для скриптов/cron).",
        )

    def handle(self, *args, **options):
        if options["bot_only"] and options["site_only"]:
            raise CommandError("Укажите только один из флагов: --bot-only или --site-only.")

        run_bot = not options["site_only"]
        run_site = not options["bot_only"]
        dry_run = options["dry_run"]

        if not dry_run and not options["no_input"]:
            targets = []
            if run_bot:
                targets.append("YooKassa Bot")
            if run_site:
                targets.append("YooKassa Site")
            self.stdout.write(
                self.style.WARNING(
                    "Боевое списание через API YooKassa: " + ", ".join(targets)
                )
            )
            confirm = input("Продолжить? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes", "д", "да"):
                raise CommandError("Отменено.")

        if dry_run:
            self.stdout.write(self.style.NOTICE("Режим dry-run — API и БД не изменяются."))

        summaries = []

        if run_bot:
            self.stdout.write(self.style.MIGRATE_HEADING("=== YooKassa Bot ==="))
            logger = ConsoleTaskRunLogger(channel="BOT", stdout=self.stdout, style=self.style)
            summary = run_ukassa_bot_recurring(logger, dry_run=dry_run)
            summaries.append(f"BOT: {summary}")

        if run_site:
            self.stdout.write(self.style.MIGRATE_HEADING("=== YooKassa Site ==="))
            logger = ConsoleTaskRunLogger(channel="SITE", stdout=self.stdout, style=self.style)
            summary = run_ukassa_site_recurring(logger, dry_run=dry_run)
            summaries.append(f"SITE: {summary}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Готово. " + " | ".join(summaries)))
