"""Выбор сервера и списка стран по протоколу ключа."""
from __future__ import annotations

from typing import Optional, Tuple

from django.conf import settings
from django.db.models import QuerySet

from apps.admindashboardx.panel_health import exclude_panel_down_servers
from bot.models import Country, Server



_PROTOCOL_ROLE = {
    "outline": (Server.NODE_ROLE_OUTLINE, "is_activated_vless"),
    "vless": (Server.NODE_ROLE_VLESS, "is_activated_vless"),
    "hysteria2": (Server.NODE_ROLE_HYSTERIA2, "is_c3celeryty_activated"),
}


def server_pools_for_protocol(protocol: str) -> Tuple[QuerySet, QuerySet]:
    """Активные серверы протокола, без panel=down: (роль, старые без роли)."""
    spec = _PROTOCOL_ROLE.get((protocol or "").strip().lower())
    if spec is None:
        empty = Server.objects.none()
        return empty, empty
    role, flag = spec
    base = exclude_panel_down_servers(Server.objects.filter(is_active=True))
    role_qs = base.filter(node_role=role, **{flag: True})
    legacy_qs = base.filter(node_role=Server.NODE_ROLE_LEGACY, **{flag: True})
    return role_qs, legacy_qs


def pick_server_for_protocol(country: Country, protocol: str) -> Optional[Server]:
    """Сначала сервер выбранной роли, иначе старый сервер со всеми протоколами."""
    role_qs, legacy_qs = server_pools_for_protocol(protocol)
    limit = settings.KEY_LIMIT
    server = (
        role_qs.filter(country=country, keys_generated__lte=limit)
        .order_by("keys_generated", "pk")
        .first()
    )
    if server is not None:
        return server
    return (
        legacy_qs.filter(country=country, keys_generated__lte=limit)
        .order_by("keys_generated", "pk")
        .first()
    )


def countries_for_protocol(protocol: str) -> QuerySet:
    role_qs, legacy_qs = server_pools_for_protocol(protocol)
    country_ids = set(role_qs.values_list("country_id", flat=True))
    country_ids.update(legacy_qs.values_list("country_id", flat=True))
    country_ids.discard(None)
    return Country.objects.filter(id__in=country_ids, is_active=True).order_by(
        "name_for_app", "name"
    )


def protocol_country_payload() -> dict:
    payload = {}
    for protocol in ("outline", "vless", "hysteria2"):
        payload[protocol] = [
            {
                "name": country.name or "",
                "label": country.name_for_app or country.name or "",
            }
            for country in countries_for_protocol(protocol)
            if (country.name or "").strip()
        ]
    return payload
