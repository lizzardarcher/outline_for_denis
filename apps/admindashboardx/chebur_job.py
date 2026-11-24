
"""Отдельный прогон Cheburcheck: не чаще одной ноды в 40 секунд.

Задача стартует раз в 30 минут и заканчивается за 2 минуты до следующего
запуска. Ноды, которые не успели, остаются на следующий раз: сначала те,
которых ещё не проверяли, затем с самой старой проверкой.
На выдачу ключей результат не влияет.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence

from django.utils import timezone

from apps.admindashboardx.cheburcheck import (
    STATUS_NO_ACCESS,
    CheburcheckUnavailable,
    _probe_one,
    _service_ready,
)
from bot.models import Server


GAP_SECONDS = 40
WINDOW_SECONDS = 30 * 60
BUFFER_SECONDS = 2 * 60


class PreflightFailed(Exception):
    """Cheburcheck не ответил до обхода нод."""


class _LiveProbe:
    def __init__(self):
        import requests
        from django.conf import settings

        token = (getattr(settings, "CHEBURCHECK_API_TOKEN", "") or "").strip()
        if not token:
            raise PreflightFailed("нет токена")
        self.token = token
        self.base = (getattr(settings, "CHEBURCHECK_API_BASE", "") or "https://cheburcheck.ru/api/v1").rstrip("/")
        self.session = requests.Session()
        try:
            if not _service_ready(self.session, self.base):
                raise PreflightFailed("healthcheck")
        except Exception:
            self.session.close()
            raise

    def __call__(self, ip: str) -> dict:
        return _probe_one(self.session, self.base, self.token, ip)

    def close(self) -> None:
        self.session.close()


def run_chebur_round(
    *,
    servers: Optional[Sequence] = None,
    probe_one: Optional[Callable[[str], dict]] = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    gap: int = GAP_SECONDS,
    window: int = WINDOW_SECONDS,
    buffer: int = BUFFER_SECONDS,
) -> dict:
    rows = list(servers) if servers is not None else _load_servers()
    groups = _group_by_ip(rows)
    summary = {"checked": 0, "skipped": len(groups), "api_down": False, "ok": 0, "down": 0, "question": 0, "no_access": 0}
    if not groups:
        return summary

    own_probe = probe_one is None
    if own_probe:
        try:
            probe_one = _LiveProbe()
        except PreflightFailed:
            _store_groups(groups, STATUS_NO_ACCESS, "нет доступа")
            summary["checked"] = len(groups)
            summary["skipped"] = 0
            summary["api_down"] = True
            summary["no_access"] = len(groups)
            return summary

    deadline = monotonic() + max(0, window - buffer)
    try:
        for index, (ip, group) in enumerate(groups):
            if index:
                if monotonic() + gap > deadline:
                    break
                sleep(gap)
            try:
                result = probe_one(ip)
            except CheburcheckUnavailable:
                _store_groups([(ip, group)], STATUS_NO_ACCESS, "нет доступа")
                summary["checked"] += 1
                summary["no_access"] += 1
                summary["api_down"] = True
                break
            status = str((result or {}).get("status") or "question")
            detail = str((result or {}).get("detail") or "")
            _store_groups([(ip, group)], status, detail)
            summary["checked"] += 1
            if status in ("ok", "down", "question", "no_access"):
                summary[status] += 1
        summary["skipped"] = len(groups) - summary["checked"]
        return summary
    finally:
        if own_probe and probe_one is not None:
            probe_one.close()


def _load_servers() -> List[Server]:
    return list(
        Server.objects.exclude(ip_address="").exclude(ip_address__isnull=True).only("id", "ip_address").order_by("id")
    )


def _group_by_ip(servers: Sequence) -> List[tuple]:
    from apps.admindashboardx.models import ServerHealthState

    ids = [getattr(server, "pk", None) for server in servers if getattr(server, "pk", None)]
    checked = dict(
        ServerHealthState.objects.filter(
            server_id__in=ids,
            channel=ServerHealthState.CHANNEL_CHEBUR,
        ).values_list("server_id", "last_checked_at")
    )
    groups: Dict[str, dict] = {}
    for server in servers:
        ip = (getattr(server, "ip_address", None) or "").strip()
        server_id = getattr(server, "pk", None)
        if not ip or not server_id:
            continue
        moment = checked.get(server_id)
        bucket = groups.get(ip)
        if bucket is None:
            groups[ip] = {"ids": [server_id], "checked_at": moment}
            continue
        bucket["ids"].append(server_id)
        previous = bucket["checked_at"]
        if previous is not None and (moment is None or moment < previous):
            bucket["checked_at"] = moment
    return sorted(groups.items(), key=lambda item: _age_key(item[1]["checked_at"], item[0]))


def _age_key(checked_at, ip: str):
    if checked_at is None:
        return (0, datetime.min, ip)
    return (1, checked_at, ip)


def _store_groups(groups, status: str, detail: str) -> None:
    from apps.admindashboardx.models import ServerHealthSample, ServerHealthState
    from apps.admindashboardx.panel_health import _upsert_state

    checked_at = timezone.now()
    server_ids = [server_id for _ip, group in groups for server_id in group["ids"]]
    existing = set(Server.objects.filter(pk__in=server_ids).values_list("pk", flat=True))
    for _ip, group in groups:
        for server_id in group["ids"]:
            if server_id not in existing:
                continue
            ServerHealthSample.objects.create(
                server_id=server_id,
                checked_at=checked_at,
                panel_status="",
                ping_status="",
                chebur_status=status,
                chebur_detail=(detail or "")[:300],
            )
            _upsert_state(
                ServerHealthState,
                server_id,
                ServerHealthState.CHANNEL_CHEBUR,
                status,
                detail or "",
                checked_at,
            )
