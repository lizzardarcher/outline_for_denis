"""Живой прогон Cheburcheck в консоли. В базу ничего не пишет.


Примеры:
  python manage.py cheburcheck_debug 8.8.8.8
  python manage.py cheburcheck_debug --server-id 15
  python manage.py cheburcheck_debug --limit 2
"""
from django.core.management.base import BaseCommand, CommandError

from apps.admindashboardx.cheburcheck import probe_addresses
from bot.models import Server


_MARKS = {
    "ok": "✅",
    "down": "❌",
    "question": "❓",
    "no_access": "⚠️ нет доступа",
    "idle": "нет IP",
}


class Command(BaseCommand):
    help = "Показать живую проверку Cheburcheck в консоли. Базу не меняет."

    def add_arguments(self, parser):
        parser.add_argument("ips", nargs="*", help="IPv4 или IPv6, можно несколько")
        parser.add_argument(
            "--server-id",
            action="append",
            dest="server_ids",
            type=int,
            help="id сервера из базы. Можно указать несколько раз.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Взять первые N серверов с IP из базы.",
        )

    def handle(self, *args, **options):
        ips = [item.strip() for item in options["ips"] if item and item.strip()]
        server_ids = options["server_ids"] or []
        limit = options["limit"] or 0
        if server_ids or limit:
            queryset = Server.objects.exclude(ip_address="").exclude(ip_address__isnull=True).order_by("id")
            if server_ids:
                queryset = queryset.filter(pk__in=server_ids)
            if limit:
                queryset = queryset[:limit]
            for server in queryset:
                ip = (server.ip_address or "").strip()
                if not ip:
                    continue
                self.stdout.write(f"сервер #{server.pk} {server.hosting or '—'} {ip}")
                ips.append(ip)
        if not ips:
            raise CommandError("Укажите IP, --server-id или --limit.")

        results = probe_addresses(ips, trace=self.stdout.write)
        self.stdout.write("")
        self.stdout.write("сводка")
        for ip, item in results.items():
            status = item.get("status") or ""
            mark = _MARKS.get(status, status)
            detail = item.get("detail") or ""
            self.stdout.write(f"{ip}  {mark}  {detail}")
