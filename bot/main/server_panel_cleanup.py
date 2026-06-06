"""
Удаление VPN-ноды из панелей Marzban и Celerity при удалении Server из админки.

Ошибки API не блокируют удаление записи в Django — пишем в Logging.
"""
from __future__ import annotations


from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.main.CelerityAPI import CelerityAPI
    from bot.main.MarzbanAPI import MarzbanAPI

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


def delete_server_from_panels(server: Server) -> None:
    """Вызывается перед удалением Server из БД."""
    label = _server_label(server)
    _log("INFO", f"[Server delete] Удаление нод в панелях для {label}")

    try:
        mb_deleted, mb_failed = delete_server_from_marzban(server)
    except Exception as exc:
        mb_deleted, mb_failed = 0, 1
        _log("ERROR", f"[Marzban] Исключение при удалении {label}: {exc!r}")

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
            f"Celerity deleted={ce_deleted} failed={ce_failed}"
        ),
    )
