"""
Снимок метрик Marzban и C³ Celerity для главной AdminDashboardX (активные учётки, онлайн, трафик).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.utils import dateparse
from django.utils import timezone

logger = logging.getLogger(__name__)


def marzban_error_payload(message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "users_total": None,
        "users_active": None,
        "online_24h": None,
        "traffic_used_bytes": None,
        "traffic_human": "—",
    }


def celerity_error_payload(message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "users_total": None,
        "users_enabled": None,
        "online_hint": None,
        "traffic_used_bytes": None,
        "traffic_human": "—",
        "stats_raw_keys": None,
    }


def fetch_both_panels(timeout_each: float = 14.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Параллельно опрашивает Marzban и Celerity, чтобы не удваивать время ожидания главной."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_mb = pool.submit(fetch_marzban_dashboard_metrics)
        f_ce = pool.submit(fetch_celerity_dashboard_metrics)
        try:
            mb = f_mb.result(timeout=timeout_each)
        except concurrent.futures.TimeoutError:
            mb = marzban_error_payload(f"Таймаут Marzban ({int(timeout_each)} с)")
        try:
            ce = f_ce.result(timeout=timeout_each)
        except concurrent.futures.TimeoutError:
            ce = celerity_error_payload(f"Таймаут Celerity ({int(timeout_each)} с)")
    return mb, ce

def format_bytes_human(n: Optional[int]) -> str:
    if n is None or n < 0:
        return "—"
    x = float(int(n))
    units = ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ")
    i = 0
    while x >= 1024.0 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    if i == 0:
        return f"{int(x)} {units[i]}"
    text = f"{x:.1f} {units[i]}"
    return text.replace(".0 ", " ")


def _parse_dt(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        dt = dateparse.parse_datetime(s)
        if dt is None:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _marzban_iter_users(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("users", "data", "items"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _marzban_total_from_payload(payload: Any) -> Optional[int]:
    if isinstance(payload, dict) and payload.get("total") is not None:
        try:
            return int(payload["total"])
        except (TypeError, ValueError):
            return None
    return None


def fetch_marzban_dashboard_metrics() -> Dict[str, Any]:
    """
    Marzban: все пользователи с пагинацией, сумма used_traffic, онлайн за 24 ч по online_at,
    учётные записи со status == active.
    """
    out: Dict[str, Any] = {
        "ok": False,
        "error": None,
        "users_total": None,
        "users_active": None,
        "online_24h": None,
        "traffic_used_bytes": None,
        "traffic_human": "—",
    }
    try:
        from bot.main.MarzbanAPI import MarzbanAPI

        api = MarzbanAPI()
        if not getattr(api, "api_token", None):
            out["error"] = "Нет токена Marzban (проверьте учётные данные в TelegramBot)."
            return out

        all_rows: List[dict] = []
        offset = 0
        page = 500
        reported_total: Optional[int] = None
        for _ in range(50):
            ok, payload = api.list_users(offset=offset, limit=page)
            if not ok:
                out["error"] = str(payload)[:500]
                return out
            chunk = _marzban_iter_users(payload)
            if reported_total is None:
                reported_total = _marzban_total_from_payload(payload)
            all_rows.extend(chunk)
            if len(chunk) < page:
                break
            offset += page
            if reported_total is not None and len(all_rows) >= reported_total:
                break

        now = timezone.now()
        since = now - timedelta(hours=24)
        traffic = 0
        active_n = 0
        online_n = 0
        for u in all_rows:
            try:
                traffic += int(u.get("used_traffic") or 0)
            except (TypeError, ValueError):
                pass
            st = (u.get("status") or "").lower()
            if st == "active":
                active_n += 1
            oa = u.get("online_at")
            dt = _parse_dt(oa)
            if dt and dt >= since:
                online_n += 1

        out["ok"] = True
        out["users_total"] = reported_total if reported_total is not None else len(all_rows)
        out["users_active"] = active_n
        out["online_24h"] = online_n
        out["traffic_used_bytes"] = traffic
        out["traffic_human"] = format_bytes_human(traffic)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.exception("Marzban dashboard metrics")
        out["error"] = str(exc)[:500]
        return out


def _celerity_iter_users(payload: Any) -> Tuple[List[dict], Optional[int]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)], None
    if isinstance(payload, dict):
        if payload.get("total") is not None:
            try:
                tot = int(payload["total"])
            except (TypeError, ValueError):
                tot = None
        else:
            tot = None
        for key in ("users", "data", "items"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)], tot
    return [], None


def _celerity_user_traffic_bytes(u: dict) -> int:
    t = u.get("traffic")
    if not isinstance(t, dict):
        return 0
    try:
        return int(t.get("tx") or 0) + int(t.get("rx") or 0)
    except (TypeError, ValueError):
        return 0


def _celerity_stats_pick_numbers(data: dict) -> Dict[str, Any]:
    """Пытается вытащить из GET /stats агрегаты без жёсткой схемы."""
    hints: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return hints
    lower_map = {str(k).lower(): k for k in data}
    for want in (
        ("totalusers", "users_total"),
        ("usercount", "users_total"),
        ("onlineusers", "online_total"),
        ("activeusers", "online_total"),
        ("totaltraffic", "traffic_bytes"),
        ("trafficbytes", "traffic_bytes"),
        ("traffic", "traffic_bytes"),
    ):
        lk, outk = want
        orig = lower_map.get(lk)
        if orig is None:
            continue
        val = data.get(orig)
        if isinstance(val, dict):
            for subk in ("total", "bytes", "used", "sum"):
                if subk in val and isinstance(val[subk], (int, float)):
                    hints[outk] = int(val[subk])
                    break
        elif isinstance(val, (int, float)):
            hints[outk] = int(val)
    return hints


def fetch_celerity_dashboard_metrics() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "error": None,
        "users_total": None,
        "users_enabled": None,
        "online_hint": None,
        "traffic_used_bytes": None,
        "traffic_human": "—",
        "stats_raw_keys": None,
    }
    try:
        from bot.main.CelerityAPI import CelerityAPI

        api = CelerityAPI()
        stats_hints: Dict[str, Any] = {}
        ok_s, stats_body = api.get_stats()
        if ok_s and isinstance(stats_body, dict):
            stats_hints = _celerity_stats_pick_numbers(stats_body)
            out["stats_raw_keys"] = list(stats_body.keys())[:40]

        all_rows: List[dict] = []
        reported_total: Optional[int] = None
        for offset in range(0, 10000, 200):
            ok, payload = api.list_users(params={"offset": offset, "limit": 200})
            if not ok:
                if not all_rows:
                    out["error"] = str(payload)[:500]
                    return out
                break
            chunk, tot = _celerity_iter_users(payload)
            if reported_total is None and tot is not None:
                reported_total = tot
            all_rows.extend(chunk)
            if len(chunk) < 200:
                break

        traffic = 0
        enabled_n = 0
        for u in all_rows:
            traffic += _celerity_user_traffic_bytes(u)
            if u.get("enabled") is True:
                enabled_n += 1

        out["ok"] = True
        out["users_total"] = stats_hints.get("users_total")
        if out["users_total"] is None:
            out["users_total"] = reported_total if reported_total is not None else len(all_rows)
        out["users_enabled"] = enabled_n
        out["online_hint"] = stats_hints.get("online_total")
        tb = stats_hints.get("traffic_bytes")
        if tb is not None:
            out["traffic_used_bytes"] = tb
        else:
            out["traffic_used_bytes"] = traffic
        out["traffic_human"] = format_bytes_human(out["traffic_used_bytes"])
        return out
    except Exception as exc:  # noqa: BLE001
        logger.exception("Celerity dashboard metrics")
        out["error"] = str(exc)[:500]
        return out
