"""
Новый VPS: marzban-node (ss/vless), затем Hysteria (Celerity).

Оба шага идут по SSH панели Celerity. С хоста Celery порт 22 нового VPS
часто недоступен (таймаут), а панель до него доходит — так раньше и ставилась Celerity.
"""
from __future__ import annotations

from django.db.models import Q

from bot.main.celerity_node_bootstrap import bootstrap_celerity_for_server
from bot.main.marzban_node_bootstrap import (
    build_marzban_node_install_script,
    load_marzban_client_cert,
    register_marzban_node,
)
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

    needs_vless = not server.is_activated_vless
    pin = (server.hysteria_pin_sha256 or "").strip()
    sni = (server.hysteria_tls_sni or "").strip()
    needs_hysteria = not (server.is_c3celeryty_activated and pin and sni)
    if not needs_vless and not needs_hysteria:
        return

    init_script = None
    setup_timeout = 300
    if needs_vless:
        try:
            cert_pem, source = load_marzban_client_cert()
            init_script = build_marzban_node_install_script(cert_pem)
        except Exception as exc:
            _log("ss/vless", "ERROR", f"нет client certificate: {exc}")
        else:
            _log(
                "ss/vless",
                "DEBUG",
                f"установка marzban-node через SSH панели Celerity (cert: {source})",
            )
            setup_timeout = 900

    ok, detail = bootstrap_celerity_for_server(
        server,
        init_script=init_script,
        setup_timeout=setup_timeout,
        log_fn=lambda level, msg: _log("hysteria", level, msg),
    )

    server.refresh_from_db(
        fields=[
            "is_activated_vless",
            "is_c3celeryty_activated",
            "hysteria_pin_sha256",
            "hysteria_tls_sni",
        ],
    )
    if needs_vless and "MARZBAN_NODE_UP" in (detail or "") and not server.is_activated_vless:
        ok_reg, reg_detail = register_marzban_node(server)
        if ok_reg:
            server.is_activated_vless = True
            server.save(update_fields=["is_activated_vless"])
            _log("ss/vless", "INFO", f"готово: {reg_detail}")
        else:
            _log("ss/vless", "ERROR", str(reg_detail)[:1500])
    elif needs_vless and not server.is_activated_vless:
        _log(
            "ss/vless",
            "ERROR",
            "marzban-node не подтверждён (в логе setup нет MARZBAN_NODE_UP). hysteria от этого не останавливается",
        )

    if not ok:
        _log("hysteria", "ERROR", str(detail)[:1500])
