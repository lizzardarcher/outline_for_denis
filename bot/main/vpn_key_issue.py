from __future__ import annotations

from typing import Optional, Tuple

from django.conf import settings

from bot.main.MarzbanAPI import MarzbanAPI
from bot.main.celerity_key_issue import issue_hysteria2_tls_for_user, try_delete_celerity_user
from bot.models import Country, Server, TelegramUser, VpnKey

KEY_LIMIT = settings.KEY_LIMIT



def marzban_create_and_get_user(telegram_user: TelegramUser, protocol: str) -> dict:
    uid = str(telegram_user.user_id)
    api = MarzbanAPI()
    api.delete_user(username=uid)
    create_ok, create_result = api.create_user(username=uid, protocol=protocol)
    if not create_ok:
        if isinstance(create_result, dict) and create_result.get("status_code") == 409:
            get_ok, get_result = api.get_user(username=uid)
            if get_ok and isinstance(get_result, dict):
                return get_result
        raise ValueError(f"Marzban create_user failed: {create_result}")
    get_ok, get_result = api.get_user(username=uid)
    if not get_ok or not isinstance(get_result, dict):
        raise ValueError(f"Marzban get_user failed: {get_result}")
    return get_result


def _pick_marzban_link(links: list, server: Server, protocol: str) -> str:
    ip = server.ip_address or ""
    for link in links:
        if protocol == "outline":
            if ip in link and "ss://" in link and "vless://" not in link:
                return link
        elif protocol == "vless":
            if ip in link and "vless://" in link:
                return link
    return "---"


def _upsert_vpn_key(
    *,
    user: TelegramUser,
    server: Server,
    access_url: str,
    protocol: str,
    method: str,
    port: int,
) -> VpnKey:
    key_id = str(user.user_id)
    vpn_key, _ = VpnKey.objects.update_or_create(
        key_id=key_id,
        defaults={
            "server": server,
            "user": user,
            "name": key_id,
            "password": key_id,
            "port": port,
            "method": method,
            "access_url": access_url,
            "protocol": protocol,
        },
    )
    return vpn_key


def _server_for_marzban(country: Country) -> Optional[Server]:
    return (
        Server.objects.filter(
            is_active=True,
            is_activated_vless=True,
            country=country,
            keys_generated__lte=KEY_LIMIT,
        )
        .order_by("keys_generated")
        .first()
    )


def _server_for_hysteria2(country: Country) -> Optional[Server]:
    return (
        Server.objects.filter(
            is_active=True,
            is_c3celeryty_activated=True,
            country=country,
            keys_generated__lte=KEY_LIMIT,
        )
        .order_by("keys_generated")
        .first()
    )


def issue_vpn_key_for_user(
    user: TelegramUser,
    country: Country,
    protocol: str,
) -> Tuple[bool, str, Optional[str]]:
    """
    Create or replace a VPN key for the user.

    Caller must hold ``acquire_vpn_key_create_lock(user.user_id)``.

    Returns:
        (success, user_message, access_url or None)
    """
    protocol = (protocol or "").strip().lower()

    if protocol in ("outline", "vless"):
        server = _server_for_marzban(country)
        if not server:
            return (
                False,
                f"Ошибка создания ключа! Нет доступных серверов для страны '{country.name}'.",
                None,
            )

        try_delete_celerity_user(user.user_id)
        result = marzban_create_and_get_user(user, protocol)
        access_url = _pick_marzban_link(result.get("links") or [], server, protocol)
        method = "ss" if protocol == "outline" else "vless"
        _upsert_vpn_key(
            user=user,
            server=server,
            access_url=access_url,
            protocol=protocol,
            method=method,
            port=1040,
        )
        return True, "Новый ключ создан!", access_url

    if protocol == "hysteria2":
        server = _server_for_hysteria2(country)
        if not server:
            return (
                False,
                f"Ошибка создания ключа! Нет доступных серверов Hysteria2 для страны '{country.name}'.",
                None,
            )

        ok, result = issue_hysteria2_tls_for_user(
            telegram_user_id=user.user_id,
            display_username=(user.username or str(user.user_id)),
            server_ip=(server.ip_address or "").strip(),
        )
        if not ok:
            return False, f"Ошибка создания ключа Hysteria2: {result}", None

        _upsert_vpn_key(
            user=user,
            server=server,
            access_url=result,
            protocol="hysteria2",
            method="hysteria2",
            port=443,
        )
        return True, "Новый ключ создан!", result

    return False, "Ошибка создания ключа! Неизвестный протокол.", None


def logging_context_for_protocol(protocol: str, country: Country, server: Optional[Server]) -> str:
    hosting = server.hosting if server else "-"
    country_name = server.country.name_for_app if server and server.country else country.name_for_app
    return f"[{protocol}] [{hosting}] [{country_name}]"
