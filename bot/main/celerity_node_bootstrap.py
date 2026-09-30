"""
Celerity (C³): создание ноды в панели (POST /nodes при необходимости) и установка ПО (setup).
Используется Celery-task'ами; без sys.exit и без print (ошибки — в возвращаемом значении).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional, Tuple

from django.conf import settings

from bot.main.CelerityAPI import CelerityAPI
from bot.main.celerity_key_issue import _celerity_group_id
from bot.main.hysteria_tls_meta import (
    save_hysteria_tls_meta_to_server,
    try_sync_hysteria_tls_meta_after_setup,
)
from bot.models import Server

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))
_DEFAULT_HYSTERIA_SNI = "bing.com"
_PIN_LINE = re.compile(r"HYSTERIA_PIN_SHA256=([0-9A-Fa-f]{64})")
# Второй setup: cert уже есть. Сервис идёт от User=hysteria, а каталог после
# install -D часто остаётся 700 root — отсюда tls.key permission denied.
# Права чиним до перезапуска, который делает сама панель (restartService).
HYSTERIA_PIN_INIT_SCRIPT = r"""
set -e
mkdir -p /etc/hysteria
chmod 755 /etc/hysteria
svc_user="$(sed -n 's/^User=//p' /etc/systemd/system/hysteria-server.service 2>/dev/null | tail -1)"
if [ -z "$svc_user" ] || [ "$svc_user" = "root" ]; then
  svc_user="hysteria"
fi
if [ -f /etc/hysteria/key.pem ] && id "$svc_user" >/dev/null 2>&1; then
  chown "$svc_user:$svc_user" /etc/hysteria/key.pem /etc/hysteria/cert.pem
fi
if [ -f /etc/hysteria/key.pem ]; then
  chmod 600 /etc/hysteria/key.pem
fi
if [ -f /etc/hysteria/cert.pem ]; then
  chmod 644 /etc/hysteria/cert.pem
fi
if id "$svc_user" >/dev/null 2>&1 && [ -f /etc/hysteria/key.pem ] && command -v su >/dev/null 2>&1; then
  if su -s /bin/sh "$svc_user" -c 'test -r /etc/hysteria/key.pem'; then
    echo "HYSTERIA_KEY_READABLE"
  else
    echo "HYSTERIA_KEY_NOT_READABLE"
    ls -la /etc/hysteria >&2 || true
  fi
fi
test -f /etc/hysteria/cert.pem
pin="$(openssl x509 -in /etc/hysteria/cert.pem -outform DER | sha256sum | awk '{print $1}')"
echo "HYSTERIA_PIN_SHA256=${pin}"
"""


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


def resolve_celerity_node_sni() -> str:
    """SNI маскировки Hysteria. Пустая настройка — bing.com."""
    raw = getattr(settings, "CELERITY_NODE_SNI", None)
    sni = str(raw).strip() if raw else ""
    return sni or _DEFAULT_HYSTERIA_SNI


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
    # domain включает ACME в панели и сертификат перестаёт быть self-signed CN=bing.com.
    dom = (getattr(settings, "CELERITY_NODE_DOMAIN", None) or "").strip()
    if dom:
        body["domain"] = dom
    body["sni"] = resolve_celerity_node_sni()
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

def flatten_setup_logs(data: Any) -> str:
    if isinstance(data, dict):
        logs = data.get("logs")
        if isinstance(logs, list):
            return "\n".join(str(item) for item in logs)
        if isinstance(logs, str):
            return logs
    return "" if data is None else str(data)


def pin_sha256_from_setup_logs(data: Any) -> str:
    match = _PIN_LINE.search(flatten_setup_logs(data))
    return match.group(1).upper() if match else ""


def ensure_celerity_node_sni(api: CelerityAPI, node_id: str, sni: str) -> Tuple[bool, Any]:
    """PUT только sni: панель не затирает ssh и остальные поля."""
    return api.update_node(node_id, {"sni": sni})


def mark_server_c3_activated(server: Server) -> None:
    server.is_c3celeryty_activated = True
    server.save(update_fields=["is_c3celeryty_activated"])


def _save_pin_from_logs(server: Server, data: Any, sni: str) -> str:
    pin = pin_sha256_from_setup_logs(data)
    if not pin:
        return ""
    save_hysteria_tls_meta_to_server(server, pin=pin, sni=sni)
    return pin


def hysteria_restart_looks_failed(logs_text: str) -> bool:
    """
    systemctl status после restart. Старый FATAL в journalctl не считается,
    если текущее состояние — active (running).
    """
    text = logs_text or ""
    if "Active: active (running)" in text or "server up and running" in text:
        return False
    if "Active:" in text or "permission denied" in text.lower():
        return True
    return False


def _pull_pin_via_panel_setup(
    api: CelerityAPI,
    node_id: str,
    server: Server,
    sni: str,
    emit: Callable[[str, str], None],
) -> Tuple[str, bool]:
    """
    Короткий setup: права на key.pem, pinSHA256, затем панель перезапускает hysteria-server.
    Returns (pin, restart_failed).
    """
    ok_put, err_put = api.update_node(node_id, {"initScript": HYSTERIA_PIN_INIT_SCRIPT})
    if not ok_put:
        emit("WARNING", f"PUT pin script: {err_put!r}")
        return "", False
    emit("DEBUG", "права на /etc/hysteria/key.pem и перезапуск hysteria-server")
    ok_pin, data_pin = api.setup_node(
        node_id,
        data={
            "installHysteria": False,
            "setupPortHopping": False,
            "restartService": True,
        },
        request_timeout=180,
    )
    logs_text = flatten_setup_logs(data_pin)
    api.update_node(node_id, {"initScript": ""})
    if not ok_pin:
        emit("WARNING", f"setup pin: {data_pin!r}")
        return "", hysteria_restart_looks_failed(logs_text)
    pin = _save_pin_from_logs(server, data_pin, sni)
    if "HYSTERIA_KEY_NOT_READABLE" in logs_text or hysteria_restart_looks_failed(logs_text):
        emit("ERROR", "hysteria не читает /etc/hysteria/key.pem после chown/chmod")
        return pin, True
    if "HYSTERIA_KEY_READABLE" in logs_text or "active (running)" in logs_text:
        emit("INFO", "hysteria-server запущен, key.pem доступен пользователю сервиса")
    return pin, False


def bootstrap_celerity_for_server(
    server: Server,
    *,
    api: Optional[CelerityAPI] = None,
    node_type: str = "hysteria",
    setup_timeout: int = 300,
    log_fn: Optional[Callable[[str, str], None]] = None,
    init_script: Optional[str] = None,
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

    sni = resolve_celerity_node_sni()
    node_update: dict = {"sni": sni}
    if init_script:
        node_update["initScript"] = init_script
        _emit("DEBUG", "initScript: marzban-node ставится по SSH панели Celerity, до Hysteria")
    ok_sni, err_sni = api.update_node(node_id, node_update)
    if not ok_sni:
        _emit("ERROR", f"PUT sni={sni}: {err_sni!r}")
        return False, f"PUT sni={sni}: {err_sni!r}"
    _emit("DEBUG", f"Hysteria TLS SNI={sni}")

    _emit("DEBUG", f"POST setup node_id={node_id!r} (timeout {setup_timeout}s)")
    ok_setup, data = api.setup_node(node_id, request_timeout=setup_timeout)
    logs_text = flatten_setup_logs(data)
    marzban_up = "MARZBAN_NODE_UP" in logs_text
    if not ok_setup:
        _emit("ERROR", f"setup_node: {data!r}")
        failed = f"setup_node: {data!r}"
        if marzban_up:
            failed = "MARZBAN_NODE_UP " + failed
        return False, failed

    pin = _save_pin_from_logs(server, data, sni)
    fixed_pin, restart_failed = _pull_pin_via_panel_setup(api, node_id, server, sni, _emit)
    if fixed_pin:
        pin = fixed_pin
    if pin:
        _emit("INFO", f"hysteria TLS meta: pin={pin[:8]}… sni={sni}")
    if restart_failed:
        failed = "hysteria-server не online: нет прав на /etc/hysteria/key.pem"
        if marzban_up:
            failed = "MARZBAN_NODE_UP " + failed
        return False, failed
    if not pin:
        synced = try_sync_hysteria_tls_meta_after_setup(
            server,
            log_fn=_emit,
            sni_override=sni,
            attempts=1 if init_script else 4,
        )
        if not synced:
            failed = "setup прошёл, но pinSHA256 не снят с /etc/hysteria/cert.pem"
            if marzban_up:
                failed = "MARZBAN_NODE_UP " + failed
            return False, failed

    mark_server_c3_activated(server)
    detail = "MARZBAN_NODE_UP " if marzban_up else ""
    if isinstance(data, dict) and data.get("logs"):
        detail += json.dumps(data, ensure_ascii=False, default=str)[:1500]
    _emit("INFO", "setup OK, pinSHA256 сохранён, is_c3celeryty_activated=True")
    return True, detail or "OK"
