"""Проверка IP через Cheburcheck: список блокировок и сетевые сканеры.

Токен читается из CHEBURCHECK_API_TOKEN и уходит только в заголовке
Authorization. Если API не отвечает, каждый адрес получает статус no_access.
Если API ответил, а сканеры ничего не прислали — статус question.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Dict, Iterable, List, Sequence
from urllib.parse import quote

import requests
from django.conf import settings


class CheburcheckUnavailable(Exception):
    """API Cheburcheck недоступен: сеть, авторизация или ошибка сервиса."""


STATUS_OK = "ok"
STATUS_DOWN = "down"
STATUS_QUESTION = "question"
STATUS_NO_ACCESS = "no_access"

_BLOCK_LABELS = {
    "tspu_block": "ТСПУ",
    "sni_block": "SNI",
    "dns_spoofing": "DNS",
    "cdn_block": "CDN",
}
_OK_VERDICTS = {"ok", "whitelist"}
_API_DOWN_CODES = {401, 403, 429, 500, 503, 504}

_HEALTH_TIMEOUT = (5, 5)
_CHECK_TIMEOUT = (5, 10)
_PROBE_TIMEOUT = (5, 20)

_NO_ACCESS = {"status": STATUS_NO_ACCESS, "detail": "нет доступа"}
_QUESTION = {"status": STATUS_QUESTION, "detail": "нет ответа сканеров"}



def probe_addresses(ips: Sequence[str], trace=None, gap: int = 0, sleep=None) -> Dict[str, dict]:
    unique: List[str] = []
    seen = set()
    for raw in ips:
        ip = (raw or "").strip()
        if ip and ip not in seen:
            seen.add(ip)
            unique.append(ip)
    if not unique:
        return {}

    token = (getattr(settings, "CHEBURCHECK_API_TOKEN", "") or "").strip()
    if not token:
        _say(trace, "токен не задан, запросы не отправляю")
        return {ip: dict(_NO_ACCESS) for ip in unique}

    base = (getattr(settings, "CHEBURCHECK_API_BASE", "") or "https://cheburcheck.ru/api/v1").rstrip("/")
    session = requests.Session()
    try:
        if not _service_ready(session, base, trace=trace):
            return {ip: dict(_NO_ACCESS) for ip in unique}
        if trace:
            _trace_credits(session, base, token, trace)
        results: Dict[str, dict] = {}
        api_down = False
        for index, ip in enumerate(unique):
            if index and gap and not api_down:
                _say(trace, f"пауза {gap} с")
                (sleep or _default_sleep)(gap)
            _say(trace, f"--- {ip}")
            if api_down:
                _say(trace, "пропуск: API уже недоступен")
                results[ip] = dict(_NO_ACCESS)
                continue
            try:
                results[ip] = _probe_one(session, base, token, ip, trace=trace)
            except CheburcheckUnavailable as exc:
                _say(trace, f"API недоступен: {exc}")
                api_down = True
                results[ip] = dict(_NO_ACCESS)
        return results
    finally:
        session.close()


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _say(trace, message: str) -> None:
    if trace:
        trace(message)


def _service_ready(session: requests.Session, base: str, trace=None) -> bool:
    url = f"{base}/healthcheck"
    _say(trace, f"GET {url}")
    try:
        response = session.get(url, timeout=_HEALTH_TIMEOUT)
    except requests.RequestException as exc:
        _say(trace, f"healthcheck: ошибка {exc.__class__.__name__}: {exc}")
        return False
    body = (response.text or "").strip().replace("\n", " ")[:120]
    ready = response.status_code == 200 and "ok" in (response.text or "").lower()
    _say(trace, f"healthcheck: {response.status_code} {body} -> {'ok' if ready else 'нет доступа'}")
    return ready


def _trace_credits(session: requests.Session, base: str, token: str, trace) -> None:
    url = f"{base}/credits"
    _say(trace, f"GET {url}")
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HEALTH_TIMEOUT,
        )
    except requests.RequestException as exc:
        _say(trace, f"credits: ошибка {exc.__class__.__name__}: {exc}")
        return
    _say(trace, f"credits: {response.status_code} {(response.text or '').strip()[:200]}")


def _probe_one(session: requests.Session, base: str, token: str, ip: str, trace=None) -> dict:
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {"status": STATUS_QUESTION, "detail": "некорректный адрес"}

    _say(trace, f"GET {base}/check?target={ip}")
    try:
        response = session.get(
            f"{base}/check",
            params={"target": ip},
            timeout=_CHECK_TIMEOUT,
        )
    except requests.Timeout:
        _say(trace, "check: таймаут")
        return dict(_QUESTION)
    except requests.RequestException as exc:
        raise CheburcheckUnavailable(str(exc)[:200]) from exc

    _say(trace, f"check: {response.status_code}")
    if response.status_code in _API_DOWN_CODES:
        raise CheburcheckUnavailable(f"http {response.status_code}")
    if response.status_code == 400:
        return {"status": STATUS_QUESTION, "detail": "неподдерживаемый адрес"}
    if response.status_code != 200:
        return dict(_QUESTION)

    try:
        payload = response.json()
    except ValueError:
        return dict(_QUESTION)
    if not isinstance(payload, dict):
        return dict(_QUESTION)

    blocked = bool(payload.get("blocked"))
    check_id = payload.get("id")
    shown_id = str(check_id or "")
    if len(shown_id) > 24:
        shown_id = shown_id[:24] + "…"
    _say(trace, f"check: blocked={blocked} target={payload.get('target')} id={shown_id or 'null'}")
    if not check_id:
        if blocked:
            return {"status": STATUS_DOWN, "detail": "в списке блокировок"}
        return dict(_QUESTION)

    def on_event(event, data):
        _say(trace, f"sse {event}: {_event_preview(event, data)}")

    try:
        scanner_results = _read_probe(session, base, token, str(check_id), on_event=on_event if trace else None)
    except requests.Timeout:
        _say(trace, "probe: таймаут до первого ответа")
        scanner_results = []
    result = _aggregate(blocked, scanner_results)
    _say(trace, f"итог: {result['status']} — {result['detail']}")
    return result


def _event_preview(event: str, data: str) -> str:
    if event != "result":
        text = data.replace("\n", " ")
        return text if len(text) <= 300 else text[:300] + "…"
    try:
        item = json.loads(data)
    except ValueError:
        return data[:300]
    if not isinstance(item, dict):
        return data[:300]
    brief = {
        "probe_id": item.get("probe_id"),
        "region": item.get("region"),
        "provider": item.get("provider"),
        "verdicts": item.get("verdicts"),
        "cached": item.get("cached"),
    }
    return json.dumps(brief, ensure_ascii=False)


def _read_probe(session: requests.Session, base: str, token: str, check_id: str, on_event=None) -> List[dict]:
    url = f"{base}/probe/{quote(check_id, safe='')}"
    try:
        response = session.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
            stream=True,
            timeout=_PROBE_TIMEOUT,
        )
    except requests.Timeout:
        raise
    except requests.RequestException as exc:
        raise CheburcheckUnavailable(str(exc)[:200]) from exc

    collected: List[dict] = []
    try:
        if response.status_code in _API_DOWN_CODES:
            raise CheburcheckUnavailable(f"http {response.status_code}")
        if response.status_code != 200:
            return []
        try:
            for event, data in _iter_sse(response):
                if on_event:
                    on_event(event, data)
                if event == "result":
                    try:
                        item = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(item, dict):
                        collected.append(item)
                elif event == "done":
                    break
        except requests.Timeout:
            return collected
        except requests.RequestException:
            return collected
        return collected
    finally:
        response.close()


def _iter_sse(response) -> Iterable[tuple]:
    event_name = "message"
    data_lines: List[str] = []
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = str(raw).strip()
        if line == "":
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield event_name, "\n".join(data_lines)


def _aggregate(blocked: bool, results: Sequence[dict]) -> dict:
    if not results:
        if blocked:
            return {"status": STATUS_DOWN, "detail": "в списке блокировок"}
        return dict(_QUESTION)

    labels: List[str] = []
    saw_ok = False
    saw_verdict = False
    for item in results:
        verdicts = item.get("verdicts") or []
        if not isinstance(verdicts, list):
            verdicts = []
        probe_blocks: List[str] = []
        probe_ok = False
        for verdict in verdicts:
            name = str(verdict).strip()
            if name in _BLOCK_LABELS:
                probe_blocks.append(_BLOCK_LABELS[name])
            elif name in _OK_VERDICTS:
                probe_ok = True
            elif name:
                saw_verdict = True
        if probe_blocks:
            saw_verdict = True
            for label in probe_blocks:
                if label not in labels:
                    labels.append(label)
        elif probe_ok:
            saw_ok = True
            saw_verdict = True

    if blocked and "в списке блокировок" not in labels:
        labels.insert(0, "в списке блокировок")
    if labels:
        return {"status": STATUS_DOWN, "detail": ", ".join(labels)[:300]}
    if saw_ok:
        return {"status": STATUS_OK, "detail": "доступен"}
    if saw_verdict:
        return {"status": STATUS_QUESTION, "detail": "неясно"}
    return dict(_QUESTION)
