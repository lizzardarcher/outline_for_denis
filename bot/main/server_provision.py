"""
Новый VPS: marzban-node (ss/vless), затем Hysteria (Celerity).

Оба шага идут по SSH панели Celerity. С хоста Celery порт 22 нового VPS
часто недоступен (таймаут), а панель до него доходит — так раньше и ставилась Celerity.


Сервер с node_role получает только одну панель и ufw под её порты.
Пустая роль ставится по-старому: marzban и hysteria вместе.
"""
from __future__ import annotations

from django.db.models import Q

from bot.main.celerity_node_bootstrap import (
    bootstrap_celerity_for_server,
    run_setup_init_script,
)
from bot.main.CelerityAPI import CelerityAPI
from bot.main.marzban_node_bootstrap import (
    build_marzban_node_install_script,
    load_marzban_client_cert,
    register_marzban_node,
)
from bot.main.node_firewall import build_role_init_script
from bot.models import Logging, Server


_HYSTERIA_SETUP = {
    "installHysteria": True,
    "setupPortHopping": False,
    "restartService": True,
}


def servers_pending_marzban_or_celerity():
    return (
        Server.objects.filter(is_active=True, node_role="")
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


def provision_server(server: Server, *, log_prefix: str = "[CELERY]") -> None:
    role = (server.node_role or "").strip()
    if role == Server.NODE_ROLE_HYSTERIA2:
        _provision_hysteria_role(server, log_prefix=log_prefix)
        return
    if role in (Server.NODE_ROLE_OUTLINE, Server.NODE_ROLE_VLESS):
        _provision_marzban_role(server, role, log_prefix=log_prefix)
        return
    provision_marzban_then_celerity(server, log_prefix=log_prefix)


def _role_logger(server: Server, log_prefix: str, panel: str):
    label = server.hosting or server.ip_address or f"pk={server.pk}"

    def _log(level: str, message: str) -> None:
        Logging.objects.create(
            category="vpn",
            log_level=level,
            message=f"{log_prefix} [{panel}] [{label}] {message}"[:4000],
        )

    return _log


def _provision_hysteria_role(server: Server, *, log_prefix: str) -> None:
    _log = _role_logger(server, log_prefix, "hysteria")
    try:
        init_script = build_role_init_script(Server.NODE_ROLE_HYSTERIA2)
    except ValueError as exc:
        _log("ERROR", str(exc))
        return
    ok, detail = bootstrap_celerity_for_server(
        server,
        init_script=init_script,
        setup_body=_HYSTERIA_SETUP,
        setup_timeout=900,
        log_fn=_log,
    )
    if not ok:
        _log("ERROR", str(detail)[:1500])


def _provision_marzban_role(server: Server, role: str, *, log_prefix: str) -> None:
    _log = _role_logger(server, log_prefix, "ss/vless")
    try:
        cert_pem, source = load_marzban_client_cert()
        marzban_script = build_marzban_node_install_script(cert_pem)
        init_script = build_role_init_script(role, marzban_script)
    except Exception as exc:
        _log("ERROR", f"нет client certificate или скрипта: {exc}")
        return

    _log("DEBUG", f"ufw и marzban-node через SSH панели Celerity (cert: {source})")
    api = CelerityAPI()
    _ok, detail, node_id = run_setup_init_script(
        server,
        init_script,
        api=api,
        setup_timeout=900,
        log_fn=_log,
    )
    if node_id:
        deleted, delete_detail = api.delete_node(node_id)
        if deleted:
            _log("DEBUG", "временная нода Celerity удалена")
        else:
            _log("ERROR", f"не удалось удалить временную ноду Celerity: {delete_detail!r}"[:1500])

    if "MARZBAN_NODE_UP" not in (detail or ""):
        _log("ERROR", "marzban-node не подтверждён (в логе setup нет MARZBAN_NODE_UP)")
        return

    ok_reg, reg_detail = register_marzban_node(server)
    if not ok_reg:
        _log("ERROR", str(reg_detail)[:1500])
        return
    server.is_activated_vless = True
    server.save(update_fields=["is_activated_vless"])
    _log("INFO", f"готово: {reg_detail}")
