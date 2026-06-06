"""
Удалить из Marzban и Celerity ноды, которых уже нет в Server (админке).

Примеры:
  python manage.py cleanup_orphan_panel_nodes --dry-run
  python manage.py cleanup_orphan_panel_nodes
  python manage.py cleanup_orphan_panel_nodes --marzban-only
  python manage.py cleanup_orphan_panel_nodes --celerity-only
"""
from django.core.management.base import BaseCommand, CommandError

from bot.main.server_panel_cleanup import (
    collect_known_server_ips,
    delete_orphan_panel_nodes,
)



class Command(BaseCommand):
    help = (
        "Удалить из Marzban/Celerity ноды, IP которых отсутствует в Server (админке)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать осиротевшие ноды, без удаления.",
        )
        parser.add_argument(
            "--marzban-only",
            action="store_true",
            help="Проверить/чистить только Marzban.",
        )
        parser.add_argument(
            "--celerity-only",
            action="store_true",
            help="Проверить/чистить только Celerity.",
        )

    def handle(self, *args, **options):
        if options["marzban_only"] and options["celerity_only"]:
            raise CommandError("Укажите только один из флагов: --marzban-only или --celerity-only.")

        include_marzban = not options["celerity_only"]
        include_celerity = not options["marzban_only"]
        dry_run = options["dry_run"]

        known_ips = collect_known_server_ips()
        self.stdout.write(f"Server в админке: {len(known_ips)} IP")

        try:
            result = delete_orphan_panel_nodes(
                dry_run=dry_run,
                include_marzban=include_marzban,
                include_celerity=include_celerity,
            )
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        if include_marzban:
            self._print_orphans("Marzban", result["marzban_orphans"])
        if include_celerity:
            self._print_orphans("Celerity", result["celerity_orphans"])

        if dry_run:
            total = len(result["marzban_orphans"]) + len(result["celerity_orphans"])
            if total:
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY-RUN: будет удалено нод: {total}. "
                        "Запустите без --dry-run для удаления."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("Осиротевших нод не найдено."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"Marzban deleted={result['marzban_deleted']} failed={result['marzban_failed']}, "
                f"Celerity deleted={result['celerity_deleted']} failed={result['celerity_failed']}"
            )
        )

    def _print_orphans(self, panel, orphans):
        if not orphans:
            self.stdout.write(f"{panel}: осиротевших нод нет")
            return
        self.stdout.write(f"{panel}: осиротевшие ноды ({len(orphans)}):")
        for node in orphans:
            extra = ""
            if node.get("type"):
                extra = f" type={node['type']}"
            name = node.get("name") or "—"
            self.stdout.write(
                f"  id={node['id']} ip={node['ip']} name={name!r}{extra}"
            )
