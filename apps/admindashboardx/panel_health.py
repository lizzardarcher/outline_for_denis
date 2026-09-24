
"""Снимок доступности VPN-серверов: панели Marzban/Celerity и ICMP ping.

Каждые 30 минут (и по кнопке) пишется проба. История хранится 7 дней.
Длительность статуса считается по непрерывной серии и не сбрасывается,
если панель или ping один раз не ответили (unknown).
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bot.models import Server


CACHE_KEY = "admx:server_panel_health:v1"
CACHE_TTL = 60 * 60 * 24
SAMPLE_RETENTION_DAYS = 7
PING_TIMEOUT_SEC = 2
PING_WORKERS = 32

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


def collect_and_store(*, marzban_api=None, celerity_api=None, servers=None, ping_hosts=None) -> dict:
    payload = collect_server_panel_health(
        marzban_api=marzban_api,
        celerity_api=celerity_api,
        servers=servers,
        ping_hosts=ping_hosts,
    )
    _persist_health(payload)
    purge_old_health_samples()
    cache.set(CACHE_KEY, payload, CACHE_TTL)
    return payload


def collect_server_panel_health(*, marzban_api=None, celerity_api=None, servers=None, ping_hosts=None) -> dict:
    checked_at = timezone.now()
    server_rows = list(servers) if servers is not None else _load_servers()

    marzban = _fetch_marzban_nodes(marzban_api)
    celerity = _fetch_celerity_nodes(celerity_api)
    panels_ok = bool(marzban.get("ok")) and bool(celerity.get("ok"))
    ping_map = ping_hosts if ping_hosts is not None else _ping_servers(server_rows)

    rows = []
    for server in server_rows:
        rows.append(_build_row(server, marzban, celerity, ping_map))

    rows.sort(
        key=lambda row: (
            _STATUS_SORT.get(row["status"], 9),
            (row.get("country") or "").lower(),
            (row.get("hosting") or "").lower(),
            row.get("server_id") or 0,
        )
    )

    counts = _summary_counts(rows)

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


def _build_row(server, marzban: Mapping[str, Any], celerity: Mapping[str, Any], ping_map: Mapping[str, Any]) -> dict:
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

    ping_status, ping_detail, ping_ms = _ping_result_for(ip, ping_map)

    return {
        "server_id": getattr(server, "pk", None) or getattr(server, "id", None),
        "hosting": (getattr(server, "hosting", None) or "").strip(),
        "ip_address": ip,
        "country": _country_label(server),
        "is_active": bool(getattr(server, "is_active", False)),
        "status": status,
        "detail": detail,
        "panel_status": status,
        "panel_detail": detail,
        "ping_status": ping_status,
        "ping_detail": ping_detail,
        "ping_ms": ping_ms,
    }


def _summary_counts(rows: Sequence[Mapping[str, Any]]) -> dict:
    counts = {
        "servers": len(rows),
        "ok": 0,
        "down": 0,
        "unknown": 0,
        "idle": 0,
        "ping_ok": 0,
        "ping_down": 0,
        "ping_unknown": 0,
        "ping_idle": 0,
    }
    for row in rows:
        key = row.get("status")
        if key in ("ok", "down", "unknown", "idle"):
            counts[key] += 1
        ping_key = "ping_" + str(row.get("ping_status") or "")
        if ping_key in counts:
            counts[ping_key] += 1
    return counts


def _ping_result_for(ip: str, ping_map: Mapping[str, Any]) -> Tuple[str, str, Optional[int]]:
    if not ip:
        return STATUS_IDLE, "нет IP", None
    item = ping_map.get(ip) if ping_map else None
    if not isinstance(item, Mapping):
        return STATUS_UNKNOWN, "нет проверки", None
    status = str(item.get("status") or STATUS_UNKNOWN)
    detail = str(item.get("detail") or "")
    ping_ms = item.get("ping_ms")
    if ping_ms is not None:
        try:
            ping_ms = int(ping_ms)
        except (TypeError, ValueError):
            ping_ms = None
    return status, detail, ping_ms


def _ping_servers(servers: Sequence[Any]) -> Dict[str, dict]:
    ips = []
    seen = set()
    for server in servers:
        ip = (getattr(server, "ip_address", None) or "").strip()
        if ip and ip not in seen:
            seen.add(ip)
            ips.append(ip)
    if not ips:
        return {}
    results: Dict[str, dict] = {}
    workers = min(PING_WORKERS, len(ips))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_ping_host, ip): ip for ip in ips}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                results[ip] = future.result()
            except Exception as exc:
                results[ip] = {"status": STATUS_UNKNOWN, "detail": str(exc)[:200], "ping_ms": None}
    return results


def _ping_host(ip: str) -> dict:
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {"status": STATUS_UNKNOWN, "detail": "некорректный адрес", "ping_ms": None}
    try:
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", str(PING_TIMEOUT_SEC), ip],
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_SEC + 2,
        )
    except subprocess.TimeoutExpired:
        return {"status": STATUS_DOWN, "detail": "недоступен", "ping_ms": None}
    except (FileNotFoundError, OSError) as exc:
        return {"status": STATUS_UNKNOWN, "detail": str(exc)[:200], "ping_ms": None}
    if proc.returncode != 0:
        return {"status": STATUS_DOWN, "detail": "недоступен", "ping_ms": None}
    match = re.search(r"time[=<]([\d.]+)\s*ms", proc.stdout or "")
    ping_ms = int(float(match.group(1))) if match else None
    return {"status": STATUS_OK, "detail": "доступен", "ping_ms": ping_ms}


def format_streak(started_at, now=None) -> str:
    moment = _as_aware(started_at)
    if moment is None:
        return ""
    current = now or timezone.now()
    seconds = max(0, int((current - moment).total_seconds()))
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч"
    return f"{hours // 24} дн"


def attach_duration_labels(rows: Sequence[dict], now=None) -> Sequence[dict]:
    current = now or timezone.now()
    for row in rows:
        row["panel_duration"] = format_streak(row.get("panel_streak_started_at"), current)
        row["ping_duration"] = format_streak(row.get("ping_streak_started_at"), current)
    return rows


def _as_aware(value):
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = parse_datetime(str(value))
        if moment is None:
            return None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    return moment


def purge_old_health_samples(days: int = SAMPLE_RETENTION_DAYS) -> int:
    from apps.admindashboardx.models import ServerHealthSample

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = ServerHealthSample.objects.filter(checked_at__lt=cutoff).delete()
    return deleted


def _persist_health(payload: dict) -> None:
    from apps.admindashboardx.models import ServerHealthSample, ServerHealthState

    rows = list(payload.get("rows") or [])
    server_ids = [row.get("server_id") for row in rows if row.get("server_id")]
    existing = set(Server.objects.filter(pk__in=server_ids).values_list("pk", flat=True))
    if not existing:
        return
    checked_at = _as_aware(payload.get("checked_at")) or timezone.now()
    samples = []
    for row in rows:
        server_id = row.get("server_id")
        if server_id not in existing:
            continue
        samples.append(
            ServerHealthSample(
                server_id=server_id,
                checked_at=checked_at,
                panel_status=row.get("panel_status") or STATUS_UNKNOWN,
                panel_detail=(row.get("panel_detail") or "")[:300],
                ping_status=row.get("ping_status") or STATUS_UNKNOWN,
                ping_detail=(row.get("ping_detail") or "")[:300],
                ping_ms=row.get("ping_ms"),
            )
        )
        panel_state = _upsert_state(
            ServerHealthState,
            server_id,
            ServerHealthState.CHANNEL_PANEL,
            row.get("panel_status") or STATUS_UNKNOWN,
            row.get("panel_detail") or "",
            checked_at,
        )
        ping_state = _upsert_state(
            ServerHealthState,
            server_id,
            ServerHealthState.CHANNEL_PING,
            row.get("ping_status") or STATUS_UNKNOWN,
            row.get("ping_detail") or "",
            checked_at,
        )
        _apply_state_to_row(row, "panel", panel_state)
        _apply_state_to_row(row, "ping", ping_state)
        row["status"] = row["panel_status"]
        row["detail"] = row["panel_detail"]
    if samples:
        ServerHealthSample.objects.bulk_create(samples)
    payload["summary"] = _summary_counts(rows)


def _apply_state_to_row(row: dict, prefix: str, state) -> None:
    row[f"{prefix}_status"] = state.status
    row[f"{prefix}_detail"] = state.detail
    row[f"{prefix}_streak_started_at"] = state.streak_started_at.isoformat()


def _upsert_state(model, server_id, channel, status, detail, checked_at):
    state = model.objects.filter(server_id=server_id, channel=channel).first()
    detail = (detail or "")[:300]
    if state is not None and status == STATUS_UNKNOWN and state.status != STATUS_UNKNOWN:
        state.last_checked_at = checked_at
        state.save(update_fields=["last_checked_at"])
        return state
    if state is None:
        return model.objects.create(
            server_id=server_id,
            channel=channel,
            status=status,
            detail=detail,
            streak_started_at=checked_at,
            last_checked_at=checked_at,
            last_ok_at=checked_at if status == STATUS_OK else None,
        )
    changed = state.status != status
    state.detail = detail
    state.last_checked_at = checked_at
    if changed:
        state.status = status
        state.streak_started_at = checked_at
    if status == STATUS_OK:
        state.last_ok_at = checked_at
    state.save()
    return state
