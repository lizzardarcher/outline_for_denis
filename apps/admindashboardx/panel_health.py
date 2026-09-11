"""Снимок доступности VPN-серверов по Marzban и Celerity.

Проверка ручная: GET /nodes обеих панелей, стыковка с Server по IP.
В результате — один статус на сервер, без разбивки по панелям.
"""
from __future__ import annotations


from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from bot.models import Server


CACHE_KEY = "admx:server_panel_health:v1"
CACHE_TTL = 60 * 60 * 24

STATUS_OK = "ok"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"
STATUS_IDLE = "idle"

_STATUS_SORT = {
    STATUS_DOWN: 0,
    STATUS_UNKNOWN: 1,
    STATUS_IDLE: 2,
    STATUS_OK: 3,
}

_HEALTHY_STATUSES = frozenset(
    {"connected", "online", "healthy", "up", "ok", "active"}
)
_PENDING_STATUSES = frozenset({"connecting", "syncing"})


def get_cached_snapshot() -> Optional[dict]:
    payload = cache.get(CACHE_KEY)
    if isinstance(payload, dict):
        return payload
    return None


def collect_and_store(*, marzban_api=None, celerity_api=None, servers=None) -> dict:
    payload = collect_server_panel_health(
        marzban_api=marzban_api,
        celerity_api=celerity_api,
        servers=servers,
    )
    cache.set(CACHE_KEY, payload, CACHE_TTL)
    return payload


def collect_server_panel_health(*, marzban_api=None, celerity_api=None, servers=None) -> dict:
    checked_at = timezone.now()
    server_rows = list(servers) if servers is not None else _load_servers()

    marzban = _fetch_marzban_nodes(marzban_api)
    celerity = _fetch_celerity_nodes(celerity_api)
    panels_ok = bool(marzban.get("ok")) and bool(celerity.get("ok"))

    rows = []
    for server in server_rows:
        rows.append(_build_row(server, marzban, celerity))

    rows.sort(
        key=lambda row: (
            _STATUS_SORT.get(row["status"], 9),
            (row.get("country") or "").lower(),
            (row.get("hosting") or "").lower(),
            row.get("server_id") or 0,
        )
    )

    counts = {
        "servers": len(rows),
        "ok": 0,
        "down": 0,
        "unknown": 0,
        "idle": 0,
    }
    for row in rows:
        key = row["status"]
        if key in counts:
            counts[key] += 1

    return {
        "checked_at": checked_at.isoformat(),
        "panels_ok": panels_ok,
        "summary": counts,
        "rows": rows,
    }


def _load_servers() -> List[Server]:
    return list(
        Server.objects.select_related("country").only(
            "id",
            "hosting",
            "ip_address",
            "is_active",
            "is_activated_vless",
            "is_c3celeryty_activated",
            "country__name",
            "country__name_for_app",
        ).order_by("id")
    )


def _unwrap_node_list(payload: Any) -> Optional[list]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("nodes", "items", "data"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return inner
    return None


def _stringify_error(payload: Any) -> str:
    if payload is None:
        return "ошибка запроса"
    if isinstance(payload, str):
        text = payload.strip()
        return text[:300] if text else "ошибка запроса"
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        return "ошибка запроса"
    return str(payload)[:300]


def _index_nodes_by_ip(nodes: Sequence[Any]) -> Dict[str, List[dict]]:
    by_ip: Dict[str, List[dict]] = defaultdict(list)
    for item in nodes:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("address") or item.get("ip") or "").strip()
        if not ip:
            continue
        by_ip[ip].append(item)
    return by_ip


def _fetch_marzban_nodes(api=None) -> dict:
    if not getattr(settings, "VPN_MARZBAN_ENABLED", True):
        return {"ok": True, "skipped": True, "by_ip": {}}
    try:
        from bot.main.MarzbanAPI import MarzbanAPI

        marzban = api or MarzbanAPI()
        if not getattr(marzban, "api_token", None):
            return {"ok": False, "skipped": False, "by_ip": {}, "error": "нет токена"}
        ok, data = marzban.list_nodes()
        if not ok:
            return {"ok": False, "skipped": False, "by_ip": {}, "error": _stringify_error(data)}
        nodes = _unwrap_node_list(data)
        if nodes is None:
            return {
                "ok": False,
                "skipped": False,
                "by_ip": {},
                "error": "неожиданный ответ",
            }
        return {"ok": True, "skipped": False, "by_ip": _index_nodes_by_ip(nodes)}
    except Exception as exc:
        return {"ok": False, "skipped": False, "by_ip": {}, "error": str(exc)[:300]}


def _fetch_celerity_nodes(api=None) -> dict:
    try:
        from bot.main.CelerityAPI import CelerityAPI

        celerity = api or CelerityAPI()
        ok, data = celerity.list_nodes()
        if not ok:
            return {"ok": False, "skipped": False, "by_ip": {}, "error": _stringify_error(data)}
        nodes = _unwrap_node_list(data)
        if nodes is None:
            return {
                "ok": False,
                "skipped": False,
                "by_ip": {},
                "error": "неожиданный ответ",
            }
        return {"ok": True, "skipped": False, "by_ip": _index_nodes_by_ip(nodes)}
    except Exception as exc:
        return {"ok": False, "skipped": False, "by_ip": {}, "error": str(exc)[:300]}


def _node_verdict(item: Mapping[str, Any]) -> Tuple[str, str]:
    raw = item.get("status")
    if raw is None:
        if item.get("connected") is True or item.get("online") is True:
            return STATUS_OK, "доступен"
        if item.get("connected") is False or item.get("online") is False:
            return STATUS_DOWN, "недоступен"
        if item.get("enabled") is False:
            return STATUS_DOWN, "недоступен"
        return STATUS_OK, "доступен"

    status = str(raw).strip().lower()
    if status in _HEALTHY_STATUSES:
        return STATUS_OK, "доступен"
    if status in _PENDING_STATUSES:
        return STATUS_DOWN, "недоступен"
    return STATUS_DOWN, "недоступен"


def _panel_verdict(panel: Mapping[str, Any], ip: str, expected: bool) -> Optional[str]:
    if panel.get("skipped"):
        return None
    if not panel.get("ok"):
        return STATUS_UNKNOWN if expected else None

    nodes = (panel.get("by_ip") or {}).get(ip) or []
    if not nodes:
        return STATUS_DOWN if expected else None

    for item in nodes:
        verdict, _detail = _node_verdict(item)
        if verdict != STATUS_OK:
            return STATUS_DOWN
    return STATUS_OK


def _combine_verdicts(verdicts: Iterable[str]) -> Tuple[str, str]:
    values = [item for item in verdicts if item]
    if not values:
        return STATUS_IDLE, "не в панелях"
    if STATUS_DOWN in values:
        return STATUS_DOWN, "недоступен"
    if STATUS_UNKNOWN in values:
        return STATUS_UNKNOWN, "нет ответа панели"
    return STATUS_OK, "доступен"


def _country_label(server) -> str:
    country = getattr(server, "country", None)
    if country is None:
        return ""
    return (getattr(country, "name_for_app", None) or getattr(country, "name", None) or "").strip()


def _build_row(server, marzban: Mapping[str, Any], celerity: Mapping[str, Any]) -> dict:
    ip = (getattr(server, "ip_address", None) or "").strip()
    expect_marzban = bool(getattr(server, "is_activated_vless", False))
    expect_celerity = bool(getattr(server, "is_c3celeryty_activated", False))

    if not ip:
        status, detail = STATUS_IDLE, "нет IP"
    else:
        if not expect_marzban and ip in (marzban.get("by_ip") or {}):
            expect_marzban = True
        if not expect_celerity and ip in (celerity.get("by_ip") or {}):
            expect_celerity = True
        status, detail = _combine_verdicts(
            (
                _panel_verdict(marzban, ip, expect_marzban),
                _panel_verdict(celerity, ip, expect_celerity),
            )
        )

    return {
        "server_id": getattr(server, "pk", None) or getattr(server, "id", None),
        "hosting": (getattr(server, "hosting", None) or "").strip(),
        "ip_address": ip,
        "country": _country_label(server),
        "is_active": bool(getattr(server, "is_active", False)),
        "status": status,
        "detail": detail,
    }
