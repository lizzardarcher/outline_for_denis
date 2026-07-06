"""
Удаление VPN-ноды из панелей Marzban, PasarGuard и Celerity при удалении Server из админки.

Ошибки API не блокируют удаление записи в Django — пишем в Logging.
"""
from __future__ import annotations


from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.main.CelerityAPI import CelerityAPI
    from bot.main.MarzbanAPI import MarzbanAPI
    from bot.main.PasarGuardAPI import PasarGuardAPI

from django.conf import settings

from bot.models import Logging, Server

def _server_label(server: Server) -> str:
    ip = (server.ip_address or "").strip()
    hosting = (server.hosting or "").strip()
    if hosting and ip:
        return f"{hosting} ({ip}) pk={server.pk}"
    return hosting or ip or f"pk={server.pk}"


def _log(level: str, message: str) -> None:
    Logging.objects.create(category="vpn", log_level=level, message=message)


def _delete_nodes_by_ids(
    panel: str,
    label: str,
    node_ids: List,
    delete_fn: Callable,
) -> Tuple[int, int]:
    deleted = 0
    failed = 0
    for node_id in node_ids:
        ok, err = delete_fn(node_id)
        if ok:
            deleted += 1
            _log("INFO", f"[{panel}] Нода {node_id} удалена для {label}")
            continue
        failed += 1
        err_text = str(err) if err is not None else "unknown error"
        if "404" in err_text or "not found" in err_text.lower():
            _log("DEBUG", f"[{panel}] Нода {node_id} уже отсутствует для {label}")
            continue
        _log("WARNING", f"[{panel}] Не удалось удалить ноду {node_id} для {label}: {err_text}")
    return deleted, failed


def delete_server_from_marzban(
    server: Server,
    *,
    api: Optional["MarzbanAPI"] = None,
) -> Tuple[int, int]:
    from bot.main.MarzbanAPI import MarzbanAPI

    ip = (server.ip_address or "").strip()
    label = _server_label(server)
    if not ip:
        _log("DEBUG", f"[Marzban] Пропуск удаления для {label}: пустой ip_address")
        return 0, 0

    marzban = api or MarzbanAPI()
    ok, data = marzban.find_node_ids_by_ip(ip)
    if not ok:
        _log("DEBUG", f"[Marzban] Нода не найдена для {label}: {data}")
        return 0, 0

    return _delete_nodes_by_ids("Marzban", label, data, marzban.delete_node)


def delete_server_from_celerity(
    server: Server,
    *,
    api: Optional["CelerityAPI"] = None,
) -> Tuple[int, int]:
    from bot.main.CelerityAPI import CelerityAPI

    ip = (server.ip_address or "").strip()
    label = _server_label(server)
    if not ip:
        _log("DEBUG", f"[Celerity] Пропуск удаления для {label}: пустой ip_address")
        return 0, 0

    celerity = api or CelerityAPI()
    ok, data = celerity.find_node_ids_by_ip(ip)
    if not ok:
        _log("DEBUG", f"[Celerity] Нода не найдена для {label}: {data}")
        return 0, 0

    return _delete_nodes_by_ids("Celerity", label, data, celerity.delete_node)


def delete_server_from_pasarguard(
    server: Server,
    *,
    api: Optional["PasarGuardAPI"] = None,
) -> Tuple[int, int]:
    from bot.main.PasarGuardAPI import PasarGuardAPI

    ip = (server.ip_address or "").strip()
    label = _server_label(server)
    if not ip:
        _log("DEBUG", f"[PasarGuard] Пропуск удаления для {label}: пустой ip_address")
        return 0, 0

    panel = api or PasarGuardAPI()
    ok, data = panel.find_node_ids_by_ip(ip)
    if not ok:
        _log("DEBUG", f"[PasarGuard] Нода не найдена для {label}: {data}")
        return 0, 0

    return _delete_nodes_by_ids("PasarGuard", label, data, panel.delete_node)


def delete_server_from_panels(server: Server) -> None:
    """Вызывается перед удалением Server из БД."""
    label = _server_label(server)
    _log("INFO", f"[Server delete] Удаление нод в панелях для {label}")

    try:
        if getattr(settings, "VPN_MARZBAN_ENABLED", True):
            mb_deleted, mb_failed = delete_server_from_marzban(server)
        else:
            mb_deleted, mb_failed = 0, 0
    except Exception as exc:
        mb_deleted, mb_failed = 0, 1
        _log("ERROR", f"[Marzban] Исключение при удалении {label}: {exc!r}")

    try:
        pg_deleted, pg_failed = delete_server_from_pasarguard(server)
    except Exception as exc:
        pg_deleted, pg_failed = 0, 1
        _log("ERROR", f"[PasarGuard] Исключение при удалении {label}: {exc!r}")

    try:
        ce_deleted, ce_failed = delete_server_from_celerity(server)
    except Exception as exc:
        ce_deleted, ce_failed = 0, 1
        _log("ERROR", f"[Celerity] Исключение при удалении {label}: {exc!r}")

    _log(
        "INFO",
        (
            f"[Server delete] Готово для {label}: "
            f"Marzban deleted={mb_deleted} failed={mb_failed}, "
            f"PasarGuard deleted={pg_deleted} failed={pg_failed}, "
            f"Celerity deleted={ce_deleted} failed={ce_failed}"
        ),
    )


def collect_known_server_ips() -> set:
    """IP-адреса всех Server в админке (непустые, без пробелов по краям)."""
    ips = set()
    for raw in (
        Server.objects.exclude(ip_address__isnull=True)
        .exclude(ip_address="")
        .values_list("ip_address", flat=True)
    ):
        needle = (raw or "").strip()
        if needle:
            ips.add(needle)
    return ips


def iter_marzban_panel_nodes(api=None):
    from bot.main.MarzbanAPI import MarzbanAPI

    marzban = api or MarzbanAPI()
    ok, data = marzban.list_nodes()
    if not ok:
        raise RuntimeError(f"Marzban list_nodes: {data!r}")

    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        ip = str(item.get("address") or item.get("ip") or "").strip()
        if raw_id is None or not ip:
            continue
        yield {
            "id": int(raw_id),
            "ip": ip,
            "name": str(item.get("name") or "").strip(),
        }


def iter_celerity_panel_nodes(api=None):
    from bot.main.CelerityAPI import CelerityAPI

    celerity = api or CelerityAPI()
    ok, data = celerity.list_nodes()
    if not ok:
        raise RuntimeError(f"Celerity list_nodes: {data!r}")
    if not isinstance(data, list):
        raise RuntimeError(f"Celerity list_nodes: неожиданный ответ {type(data).__name__}")

    for item in data:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        node_id = CelerityAPI._extract_group_id(item)
        if not ip or not node_id:
            continue
        yield {
            "id": node_id,
            "ip": ip,
            "name": str(item.get("name") or "").strip(),
            "type": str(item.get("type") or "hysteria").strip(),
        }


def iter_pasarguard_panel_nodes(api=None):
    from bot.main.PasarGuardAPI import PasarGuardAPI

    panel = api or PasarGuardAPI()
    ok, data = panel.list_nodes()
    if not ok:
        raise RuntimeError(f"PasarGuard list_nodes: {data!r}")

    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        ip = str(item.get("address") or item.get("ip") or "").strip()
        if raw_id is None or not ip:
            continue
        yield {
            "id": int(raw_id),
            "ip": ip,
            "name": str(item.get("name") or "").strip(),
        }


def find_orphan_panel_nodes(
    known_ips=None,
    *,
    marzban_api=None,
    pasarguard_api=None,
    celerity_api=None,
    include_marzban=True,
    include_pasarguard=True,
    include_celerity=True,
):
    """
    Ноды в панелях, IP которых нет ни у одного Server в Django.

    Returns:
        (marzban_orphans, pasarguard_orphans, celerity_orphans)
    """
    known = known_ips if known_ips is not None else collect_known_server_ips()

    marzban_orphans = []
    if include_marzban and getattr(settings, "VPN_MARZBAN_ENABLED", True):
        for node in iter_marzban_panel_nodes(marzban_api):
            if node["ip"] not in known:
                marzban_orphans.append(node)

    pasarguard_orphans = []
    if include_pasarguard:
        for node in iter_pasarguard_panel_nodes(pasarguard_api):
            if node["ip"] not in known:
                pasarguard_orphans.append(node)

    celerity_orphans = []
    if include_celerity:
        for node in iter_celerity_panel_nodes(celerity_api):
            if node["ip"] not in known:
                celerity_orphans.append(node)

    return marzban_orphans, pasarguard_orphans, celerity_orphans


def delete_orphan_panel_nodes(
    *,
    dry_run=False,
    include_marzban=True,
    include_pasarguard=True,
    include_celerity=True,
    marzban_api=None,
    pasarguard_api=None,
    celerity_api=None,
) -> dict:
    """
    Удаляет из Marzban/PasarGuard/Celerity ноды, IP которых отсутствует в Server.
    """
    from bot.main.CelerityAPI import CelerityAPI
    from bot.main.MarzbanAPI import MarzbanAPI
    from bot.main.PasarGuardAPI import PasarGuardAPI

    marzban_orphans, pasarguard_orphans, celerity_orphans = find_orphan_panel_nodes(
        marzban_api=marzban_api,
        pasarguard_api=pasarguard_api,
        celerity_api=celerity_api,
        include_marzban=include_marzban,
        include_pasarguard=include_pasarguard,
        include_celerity=include_celerity,
    )

    result = {
        "marzban_orphans": marzban_orphans,
        "pasarguard_orphans": pasarguard_orphans,
        "celerity_orphans": celerity_orphans,
        "marzban_deleted": 0,
        "marzban_failed": 0,
        "pasarguard_deleted": 0,
        "pasarguard_failed": 0,
        "celerity_deleted": 0,
        "celerity_failed": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    if marzban_orphans and getattr(settings, "VPN_MARZBAN_ENABLED", True):
        marzban = marzban_api or MarzbanAPI()
        for node in marzban_orphans:
            label = f"{node['name'] or node['ip']} ({node['ip']})"
            deleted, failed = _delete_nodes_by_ids(
                "Marzban",
                label,
                [node["id"]],
                marzban.delete_node,
            )
            result["marzban_deleted"] += deleted
            result["marzban_failed"] += failed

    if pasarguard_orphans:
        panel = pasarguard_api or PasarGuardAPI()
        for node in pasarguard_orphans:
            label = f"{node['name'] or node['ip']} ({node['ip']})"
            deleted, failed = _delete_nodes_by_ids(
                "PasarGuard",
                label,
                [node["id"]],
                panel.delete_node,
            )
            result["pasarguard_deleted"] += deleted
            result["pasarguard_failed"] += failed

    if celerity_orphans:
        celerity = celerity_api or CelerityAPI()
        for node in celerity_orphans:
            label = f"{node['name'] or node['ip']} ({node['ip']}) type={node.get('type', '')}"
            deleted, failed = _delete_nodes_by_ids(
                "Celerity",
                label,
                [node["id"]],
                celerity.delete_node,
            )
            result["celerity_deleted"] += deleted
            result["celerity_failed"] += failed

    _log(
        "INFO",
        (
            "[Orphan cleanup] "
            f"Marzban deleted={result['marzban_deleted']} failed={result['marzban_failed']}, "
            f"PasarGuard deleted={result['pasarguard_deleted']} failed={result['pasarguard_failed']}, "
            f"Celerity deleted={result['celerity_deleted']} failed={result['celerity_failed']}"
        ),
    )
    return result
