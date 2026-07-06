"""
Выдача VLESS / Outline через панель PasarGuard.

Политика: delete + create при каждой выдаче (как Marzban).
"""

from __future__ import annotations

from bot.main.PasarGuardAPI import PasarGuardAPI
from bot.models import Server, TelegramUser


def try_delete_pasarguard_user(telegram_user_id) -> None:
    """DELETE /user в PasarGuard; ошибки не пробрасываются."""
    try:
        PasarGuardAPI().delete_user(str(telegram_user_id))
    except Exception:
        pass


def pasarguard_create_and_get_user(telegram_user: TelegramUser, protocol: str) -> dict:
    uid = str(telegram_user.user_id)
    api = PasarGuardAPI()
    api.delete_user(username=uid)
    create_ok, create_result = api.create_user(username=uid, protocol=protocol)
    if not create_ok:
        if isinstance(create_result, dict) and create_result.get("status_code") == 409:
            get_ok, get_result = api.get_user(username=uid)
            if get_ok and isinstance(get_result, dict):
                return get_result
        raise ValueError(f"PasarGuard create_user failed: {create_result}")
    get_ok, get_result = api.get_user(username=uid)
    if not get_ok or not isinstance(get_result, dict):
        raise ValueError(f"PasarGuard get_user failed: {get_result}")
    return get_result


def pick_pasarguard_link(links: list, server: Server, protocol: str) -> str:
    ip = server.ip_address or ""
    for link in links:
        if protocol == "outline":
            if ip in link and "ss://" in link and "vless://" not in link:
                return link
        elif protocol == "vless":
            if ip in link and "vless://" in link:
                return link
    return "---"
