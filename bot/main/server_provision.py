"""
Порядок для нового VPS: сначала marzban-node (ss/vless), затем Celerity (hysteria).
Hysteria не стартует, пока панель Vless/SS не отмечена.
"""
from __future__ import annotations

from django.db.models import Q

from bot.main.celerity_node_bootstrap import bootstrap_celerity_for_server
from bot.main.marzban_node_bootstrap import bootstrap_marzban_for_server
from bot.models import Logging, Server



def servers_pending_marzban_or_celerity():
    return (
        Server.objects.filter(is_active=True)
        .filter(
            Q(is_activated_vless=False)
            | Q(is_c3celeryty_activated=False)
            | Q(hysteria_pin_sha256="")
            | Q(hysteria_tls_sni="")
        )
        .select_related("country")
    )


def provision_marzban_then_celerity(server: Server, *, log_prefix: str = "[CELERY]") -> None:
    label = server.hosting or server.ip_address or f"pk={server.pk}"

    def _log(panel: str, level: str, message: str) -> None:
        Logging.objects.create(
            category="vpn",
            log_level=level,
            message=f"{log_prefix} [{panel}] [{label}] {message}"[:4000],
        )

    if not server.is_activated_vless:
        ok, detail = bootstrap_marzban_for_server(
            server,
            log_fn=lambda level, msg: _log("ss/vless", level, msg),
        )
        if not ok:
            _log(
                "ss/vless",
                "ERROR",
                f"hysteria пропущена, ss/vless не готов: {detail}"[:3500],
            )
            return
        server.refresh_from_db(
            fields=[
                "is_activated_vless",
                "is_c3celeryty_activated",
                "hysteria_pin_sha256",
                "hysteria_tls_sni",
            ],
        )

    pin = (server.hysteria_pin_sha256 or "").strip()
    sni = (server.hysteria_tls_sni or "").strip()
    if server.is_c3celeryty_activated and pin and sni:
        return

    bootstrap_celerity_for_server(
        server,
        log_fn=lambda level, msg: _log("hysteria", level, msg),
    )
