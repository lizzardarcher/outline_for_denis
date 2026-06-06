"""
Celerity (C³): создание ноды в панели (POST /nodes при необходимости) и установка ПО (setup).
Используется Celery-task'ами; без sys.exit и без print (ошибки — в возвращаемом значении).
"""
from __future__ import annotations


import json
from typing import Any, Callable, Optional, Tuple

from django.conf import settings

from bot.main.CelerityAPI import CelerityAPI
from bot.main.celerity_key_issue import _celerity_group_id
from bot.main.hysteria_tls_meta import try_sync_hysteria_tls_meta_after_setup
from bot.models import Server

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))


def _flag_from_country_name_for_app(name: Optional[str]) -> str:
    if not name:
        return ""
    s = name.rstrip()
    if not s:
        return ""
    if len(s) >= 2:
        o2, o1 = ord(s[-2]), ord(s[-1])
        if 0x1F1E6 <= o2 <= 0x1F1FF and 0x1F1E6 <= o1 <= 0x1F1FF:
            return s[-2:]
    return s[-1]


def _flag_emoji_for_server(server: Server) -> str:
    country = getattr(server, "country", None)
    if country is None:
        return ""
    return _flag_from_country_name_for_app(
        getattr(country, "name_for_app", None) or ""
    )


def django_ssh_looks_weak(server: Server) -> bool:
    pwd = (server.password or "").strip()
    return not pwd or pwd in _SERVER_PASSWORD_PLACEHOLDERS


def build_celerity_node_payload(server: Server, group_id: str, node_type: str) -> dict:
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("У Server пустой ip_address")
    name = (server.hosting or "").strip() or f"server-{server.pk}-{ip}"

    ssh_user = (server.user or "root").strip() or "root"
    ssh_password = (server.password or "").strip()
    key_pem = (getattr(settings, "CELERITY_SSH_PRIVATE_KEY", None) or "").strip()

    if ssh_password in _SERVER_PASSWORD_PLACEHOLDERS:
        ssh_password = ""
    if not ssh_password and not key_pem:
        raise ValueError(
            f"Нужен SSH пароль в Server.password или PEM в CELERITY_SSH_PRIVATE_KEY (pk={server.pk})"
        )

    ssh_obj: dict = {
        "port": int(getattr(settings, "CELERITY_SSH_PORT", None) or 22),
        "username": ssh_user,
    }
    if ssh_password:
        ssh_obj["password"] = ssh_password
    if key_pem:
        ssh_obj["privateKey"] = key_pem

    flag = _flag_emoji_for_server(server)

    body: dict = {
        "type": node_type,
        "name": name,
        "ip": ip,
        "port": int(getattr(settings, "CELERITY_NODE_PORT", None) or 443),
        "groups": [group_id],
        "ssh": ssh_obj,
    }
    if flag:
        body["flag"] = flag
    dom = getattr(settings, "CELERITY_NODE_DOMAIN", None)
    if dom:
        body["domain"] = dom
    sni = getattr(settings, "CELERITY_NODE_SNI", None)
    if sni:
        body["sni"] = sni
    return body


def create_celerity_node_or_find(
    api: CelerityAPI,
    server: Server,
    group_id: str,
    node_type: str,
    ip: str,
) -> Tuple[bool, str, Any]:
    try:
        body = build_celerity_node_payload(server, group_id, node_type)
    except ValueError as e:
        return False, "", str(e)

    ok_c, res_c = api.create_node(body)
    if ok_c and isinstance(res_c, dict):
        nid = CelerityAPI._extract_group_id(res_c)
        if nid:
            return True, nid, None
        ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
        if ok_f:
            return True, nid2, None
        return False, "", "create OK, но нет _id в ответе и find не удался"

    err_text = res_c
    if isinstance(res_c, dict):
        err_text = res_c.get("error", res_c)
        if isinstance(err_text, str) and "already exists" in err_text.lower():
            ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
            if ok_f:
                return True, nid2, None
            return False, "", f"duplicate but find failed: {nid2!r}"

    return False, "", res_c

def mark_server_c3_activated(server: Server) -> None:
    server.is_c3celeryty_activated = True
    server.save(update_fields=["is_c3celeryty_activated"])


def bootstrap_celerity_for_server(
    server: Server,
    *,
    api: Optional[CelerityAPI] = None,
    node_type: str = "hysteria",
    setup_timeout: int = 300,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Tuple[bool, str]:
    """
    provision + setup для одного Server. При успехе — is_c3celeryty_activated=True.

    log_fn(level, message) — опционально (например для Logging в БД).
    """
    def _emit(level: str, msg: str) -> None:
        if log_fn:
            log_fn(level, msg)

    ip = (server.ip_address or "").strip()
    if not ip:
        _emit("ERROR", "пустой ip_address")
        return False, "Пустой ip_address"

    if django_ssh_looks_weak(server):
        _emit("WARNING", "пустой или заглушечный SSH password")
        return False, "Пустой или заглушечный SSH password"

    api = api or CelerityAPI()

    try:
        group_id = _celerity_group_id(api)
    except RuntimeError as e:
        _emit("ERROR", str(e))
        return False, str(e)

    ok_find, node_id = api.find_node_id_by_ip(ip, node_type)
    if not ok_find:
        _emit("DEBUG", "POST /nodes (создание ноды)")
        ok_c, nid, err_c = create_celerity_node_or_find(
            api, server, group_id, node_type, ip
        )
        if not ok_c:
            _emit("ERROR", f"create_node: {err_c!r}")
            return False, f"create_node: {err_c!r}"
        node_id = nid
    else:
        _emit("DEBUG", f"нода уже в панели node_id={node_id!r}")

    _emit("DEBUG", f"POST setup node_id={node_id!r} (timeout {setup_timeout}s)")
    ok_setup, data = api.setup_node(node_id, request_timeout=setup_timeout)
    if not ok_setup:
        _emit("ERROR", f"setup_node: {data!r}")
        return False, f"setup_node: {data!r}"

    try_sync_hysteria_tls_meta_after_setup(server, log_fn=_emit)
    mark_server_c3_activated(server)
    detail = ""
    if isinstance(data, dict) and data.get("logs"):
        detail = json.dumps(data, ensure_ascii=False, default=str)[:2000]
    _emit("INFO", "setup OK, is_c3celeryty_activated=True")
    return True, detail or "OK"
