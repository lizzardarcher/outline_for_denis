"""
Снять pinSHA256 и SNI с /etc/hysteria/cert.pem на Celerity-нодах и сохранить в Server.
Примеры:
  python manage.py sync_hysteria_tls_meta
  python manage.py sync_hysteria_tls_meta --ip 217.65.79.212
  python manage.py sync_hysteria_tls_meta --all-active
"""
from django.core.management.base import BaseCommand

from bot.main.hysteria_tls_meta import sync_hysteria_tls_meta_for_server
from bot.models import Server


class Command(BaseCommand):
    help = "Sync Hysteria TLS pin/SNI from /etc/hysteria/cert.pem via SSH into Server records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ip",
            action="append",
            dest="ips",
            default=None,
            help="IP ноды (можно указать несколько раз).",
        )
        parser.add_argument(
            "--server-id",
            action="append",
            dest="server_ids",
            default=None,
            type=int,
            help="PK Server (можно несколько).",
        )
        parser.add_argument(
            "--all-active",
            action="store_true",
            help="Все Server с is_c3celeryty_activated=True.",
        )

    def handle(self, *args, **options):
        qs = Server.objects.all().order_by("pk")
        if options.get("server_ids"):
            qs = qs.filter(pk__in=options["server_ids"])
        if options.get("ips"):
            qs = qs.filter(ip_address__in=options["ips"])
        if options.get("all_active"):
            qs = qs.filter(is_c3celeryty_activated=True)
        elif not options.get("server_ids") and not options.get("ips"):
            qs = qs.filter(is_c3celeryty_activated=True)

        servers = list(qs)
        if not servers:
            self.stdout.write(self.style.WARNING("Нет серверов для синхронизации."))
            return

        ok_n = 0
        fail_n = 0
        for server in servers:
            label = f"pk={server.pk} ip={server.ip_address!r}"
            ok, detail = sync_hysteria_tls_meta_for_server(server)
            if ok:
                ok_n += 1
                self.stdout.write(self.style.SUCCESS(f"OK {label}: {detail}"))
            else:
                fail_n += 1
                self.stdout.write(self.style.ERROR(f"FAIL {label}: {detail}"))

        self.stdout.write(f"Готово: OK={ok_n}, FAIL={fail_n}")
