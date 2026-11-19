
"""
Сохранение obfs через форму панели Celerity.

PUT /api/nodes/:id это поле молча выбрасывает: его нет в allowlist.
Пишет только POST /panel/nodes/:id под сессией администратора.
Пароль obfs в лог и в текст ошибки не попадает.
"""
from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple
from urllib.parse import quote

import requests
from django.conf import settings


MISSING_PANEL_LOGIN = (
    "API Celerity не сохраняет obfs. "
    "Укажите CELERITY_PANEL_USERNAME и CELERITY_PANEL_PASSWORD "
    "(логин этой панели) и снова запустите инициализацию. "
    "Карточку ноды вручную править не нужно"
)

_SESSION_TTL_SECONDS = 600
_session_cache: dict = {"session": None, "expires": 0.0}


def reset_panel_session_cache() -> None:
    _session_cache["session"] = None
    _session_cache["expires"] = 0.0


def panel_origin() -> str:
    raw = (getattr(settings, "C3CELERYTY_API_ENDPOINT", None) or "").strip().rstrip("/")
    if raw.endswith("/api"):
        return raw[:-4]
    return raw


def panel_credentials() -> Tuple[str, str]:
    username = (getattr(settings, "CELERITY_PANEL_USERNAME", None) or "").strip()
    password = getattr(settings, "CELERITY_PANEL_PASSWORD", None) or ""
    return username, str(password)


def _node_document(payload: Any) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("node"), dict):
        return payload["node"]
    return payload if isinstance(payload, dict) else {}


def obfs_form_fields(payload: Any, obfs_password: str) -> List[Tuple[str, str]]:
    """Поля формы редактирования. Пустой пароль SSH не отправляем: панель затрёт его."""
    doc = _node_document(payload)
    fields: List[Tuple[str, str]] = [
        ("name", str(doc.get("name") or "").strip()),
        ("ip", str(doc.get("ip") or "").strip()),
        ("type", str(doc.get("type") or "hysteria")),
        ("domain", str(doc.get("domain") or "")),
        ("sni", str(doc.get("sni") or "")),
        ("port", str(doc.get("port") or 443)),
        ("portRange", str(doc.get("portRange") or "20000-50000")),
        ("statsPort", str(doc.get("statsPort") or 9999)),
        ("rankingCoefficient", str(doc.get("rankingCoefficient") if doc.get("rankingCoefficient") is not None else 1)),
        ("country", str(doc.get("country") or "")),
        ("comment", str(doc.get("comment") or "")),
        ("flag", str(doc.get("flag") or "")),
        ("cascadeRole", str(doc.get("cascadeRole") or "standalone")),
        ("maxOnlineUsers", str(doc.get("maxOnlineUsers") or 0)),
        ("active", "on"),
        ("obfs.type", "salamander"),
        ("obfs.password", obfs_password),
    ]
    init_script = doc.get("initScript")
    if isinstance(init_script, str) and init_script.strip():
        fields.append(("initScript", init_script))
    for group in doc.get("groups") or []:
        group_id = group.get("_id") if isinstance(group, dict) else group
        if group_id:
            fields.append(("groups", str(group_id)))
    masquerade = doc.get("masquerade") if isinstance(doc.get("masquerade"), dict) else {}
    proxy = masquerade.get("proxy") if isinstance(masquerade.get("proxy"), dict) else {}
    proxy_url = str(proxy.get("url") or "").strip()
    if proxy_url:
        fields.append(("masquerade.type", str(masquerade.get("type") or "proxy")))
        fields.append(("masquerade.proxy.url", proxy_url))
        if proxy.get("rewriteHost"):
            fields.append(("masquerade.proxy.rewriteHost", "on"))
    return fields


def _login(origin: str, username: str, password: str) -> Tuple[Optional[requests.Session], str]:
    session = requests.Session()
    try:
        response = session.post(
            f"{origin}/api/login",
            json={"username": username, "password": password},
            timeout=30,
        )
    except requests.RequestException as exc:
        return None, f"панель Celerity недоступна: {exc.__class__.__name__}"
    if response.status_code == 403:
        return None, "панель отклонила вход с сервера приложения (403). Разрешите этот IP в whitelist панели"
    if response.status_code == 202:
        return None, "на входе панели включена 2FA. Для этого логина её нужно выключить: код в инициализацию не передать"
    if response.status_code == 401:
        return None, "панель не приняла CELERITY_PANEL_USERNAME или CELERITY_PANEL_PASSWORD"
    if response.status_code != 200:
        return None, f"вход в панель вернул {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict) or not body.get("success"):
        return None, "панель не открыла сессию"
    return session, ""


def _post_obfs_form(
    session: requests.Session,
    origin: str,
    node_id: str,
    fields: List[Tuple[str, str]],
) -> Tuple[bool, str]:
    url = f"{origin}/panel/nodes/{quote(str(node_id), safe='')}"
    try:
        response = session.post(url, data=fields, timeout=90, allow_redirects=True)
    except requests.RequestException as exc:
        return False, f"форма ноды не ответила: {exc.__class__.__name__}"
    final_url = str(response.url or "")
    if response.status_code == 403:
        return False, "панель отклонила сохранение ноды (403)"
    if "/panel/login" in final_url or "/api/login" in final_url:
        return False, "сессия панели истекла"
    if response.status_code >= 400:
        return False, f"форма ноды вернула {response.status_code}"
    return True, "форма панели приняла obfs"


def save_node_obfs_via_panel(node_id: str, payload: Any, obfs_password: str) -> Tuple[bool, str]:
    username, password = panel_credentials()
    if not username or not password:
        return False, MISSING_PANEL_LOGIN
    if not obfs_password:
        return False, "пустой пароль obfs"
    origin = panel_origin()
    if not origin:
        return False, "C3CELERYTY_API_ENDPOINT не задан"
    doc = _node_document(payload)
    if not str(doc.get("name") or "").strip():
        return False, "GET ноды не вернул имя, форму сохранить нельзя"
    fields = obfs_form_fields(payload, obfs_password)
    if not any(key == "groups" for key, _value in fields):
        return False, "GET ноды не вернул группу, форму не отправляю: пустая форма сняла бы ноду с группы"

    now = time.time()
    session = _session_cache["session"] if _session_cache["expires"] > now else None
    if session is None:
        session, error = _login(origin, username, password)
        if session is None:
            reset_panel_session_cache()
            return False, error
        _session_cache["session"] = session
        _session_cache["expires"] = now + _SESSION_TTL_SECONDS

    ok, detail = _post_obfs_form(session, origin, node_id, fields)
    if ok or detail != "сессия панели истекла":
        return ok, detail
    reset_panel_session_cache()
    session, error = _login(origin, username, password)
    if session is None:
        return False, error
    _session_cache["session"] = session
    _session_cache["expires"] = time.time() + _SESSION_TTL_SECONDS
    return _post_obfs_form(session, origin, node_id, fields)
