from __future__ import annotations


import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

from django.core.cache import cache

from bot.main.utils import markup, msg
from bot.models import Country, TelegramUser, VpnKey

UI_SCREEN_CACHE_PREFIX = "bot_ui_screen:"
UI_SCREEN_TTL = 120


PROTOCOL_LABELS = {
    "outline": "OUTLINE",
    "vless": "VLESS",
    "hysteria2": "Hysteria2",
}


def breadcrumb(*parts: str) -> str:
    return " › ".join(parts) + "\n\n"


def format_screen(body: str, trail: Sequence[str]) -> str:
    if not trail:
        return body
    return breadcrumb(*trail) + body


def _protocol_label(protocol: str) -> str:
    return PROTOCOL_LABELS.get((protocol or "").lower(), (protocol or "").upper())


def _country_display(country_name: str) -> str:
    country = Country.objects.filter(name=country_name).first()
    if country and country.name_for_app:
        return country.name_for_app
    return country_name


def trail_for_callback(call_data: str, data: list) -> Tuple[str, ...]:
    parts: list[str] = ["Главная"]

    if call_data in {"back", "download_app", "app_installed", "help", "common_info"}:
        return tuple(parts)

    if call_data == "profile" or call_data == "referral":
        parts.append("Профиль" if call_data == "profile" else "Реферальная программа")
        return tuple(parts)

    if call_data == "manage" or (len(data) == 1 and data[0] == "manage"):
        return ("Главная", "Управление VPN")

    if call_data.startswith("protocol_"):
        proto = call_data.replace("protocol_", "", 1)
        return ("Главная", "Управление VPN", _protocol_label(proto))

    if data and data[0] == "country" and len(data) >= 3:
        proto = data[1]
        country_name = data[2]
        return (
            "Главная",
            "Управление VPN",
            _protocol_label(proto),
            _country_display(country_name),
        )

    if call_data.startswith("withdraw:"):
        return ("Главная", "Профиль", "Реферальная программа", "Вывод")

    if call_data.startswith("tgproxy:"):
        return ("Главная", "TG Proxy")

    if data and data[0] == "account":
        if "choose_payment" in call_data:
            return ("Главная", "Подписка")
        if len(data) > 1 and data[1] == "sub":
            return ("Главная", "Подписка", "Тариф")
        if len(data) > 1 and data[1] == "payment":
            return ("Главная", "Подписка", "Оплата")
        if "cancel_subscription" in call_data:
            return ("Главная", "Профиль", "Отмена подписки")
        if "cancelled_sbs" in call_data:
            return ("Главная", "Профиль", "Подписка отменена")
        if "swap_confirm" in call_data:
            proto = data[1] if len(data) > 1 else ""
            country_name = parse_country_from_account_callback(call_data, proto)
            trail = ["Главная", "Управление VPN", _protocol_label(proto)]
            if country_name:
                trail.append(_country_display(country_name))
            trail.append("Замена ключа")
            return tuple(trail)
        if "get_new_key" in call_data or "swap_key" in call_data:
            proto = data[1] if len(data) > 1 else ""
            country_name = parse_country_from_account_callback(call_data, proto)
            trail = ["Главная", "Управление VPN", _protocol_label(proto)]
            if country_name:
                trail.append(_country_display(country_name))
            trail.append("Ключ")
            return tuple(trail)

    return tuple(parts)


def _ui_screen_key(user_id) -> str:
    return f"{UI_SCREEN_CACHE_PREFIX}{user_id}"


def set_ui_screen(user_id, kind: str, chat_id: int, message_id: int) -> None:
    cache.set(
        _ui_screen_key(user_id),
        {"kind": kind, "chat_id": chat_id, "message_id": message_id},
        timeout=UI_SCREEN_TTL,
    )


def clear_ui_screen(user_id) -> None:
    cache.delete(_ui_screen_key(user_id))


def is_ui_screen(user_id, kind: str, message_id: int) -> bool:
    payload = cache.get(_ui_screen_key(user_id))
    if not isinstance(payload, dict):
        return False
    return payload.get("kind") == kind and int(payload.get("message_id") or 0) == int(message_id)


@dataclass
class CountryKeyScreen:
    text: str
    reply_markup: Any
    menu_country: str


def active_key_summary(user: TelegramUser) -> str:
    vpn_key = (
        VpnKey.objects.filter(user=user)
        .select_related("server", "server__country")
        .first()
    )
    if not vpn_key or not vpn_key.access_url:
        return ""
    country_label = "—"
    if vpn_key.server and vpn_key.server.country:
        country_label = vpn_key.server.country.name_for_app
    proto = (vpn_key.protocol or "").upper()
    return f"<i>Активный ключ: {proto}, {country_label}</i>\n\n"


def parse_country_from_account_callback(call_data: str, protocol: str) -> str:
    """Извлекает country.name из callback вида account:{protocol}:swap_key_{country}."""
    protocol = (protocol or "").lower()
    for suffix in ("get_new_key_", "swap_key_", "swap_confirm_"):
        marker = f":{protocol}:{suffix}"
        if marker in call_data:
            return call_data.split(marker, 1)[-1]
    if "_" in call_data:
        return call_data.rsplit("_", 1)[-1]
    return call_data


def resolve_country_key_screen(
    user: TelegramUser,
    country_name: str,
    protocol: str,
) -> CountryKeyScreen:
    protocol = (protocol or "").lower()
    selected_display = _country_display(country_name)

    key = (
        VpnKey.objects.filter(user=user)
        .select_related("server", "server__country")
        .first()
    )

    if not key or not key.access_url or (key.protocol or "").lower() != protocol:
        return CountryKeyScreen(
            text=msg.get_new_key,
            reply_markup=markup.get_new_key(country_name, protocol),
            menu_country=country_name,
        )

    key_country_display = selected_display
    if key.server and key.server.country:
        key_country_display = key.server.country.name_for_app

    same_country = (
        key.server
        and key.server.country
        and key.server.country.name == country_name
    )

    if same_country:
        body = f"{msg.key_avail}\n<code>{key.access_url}</code>"
    else:
        body = (
            f"<i>Сейчас активен ключ для {key_country_display}. "
            f"Вы выбрали {selected_display}.</i>\n\n"
            f"Нажмите «Заменить ключ», чтобы выдать ключ для {selected_display}.\n\n"
            f"{msg.key_avail}\n<code>{key.access_url}</code>"
        )

    # Кнопки всегда для выбранной страны, не для страны текущего ключа.
    return CountryKeyScreen(
        text=body,
        reply_markup=markup.key_menu(country_name, protocol),
        menu_country=country_name,
    )


async def schedule_payment_reminder(bot, user_id, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(10)
    if not is_ui_screen(user_id, "payment", message_id):
        return
    try:
        await bot.edit_message_text(
            format_screen(msg.after_payment, ("Главная", "Подписка", "После оплаты")),
            chat_id,
            message_id,
            reply_markup=markup.proceed_to_profile(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    finally:
        clear_ui_screen(user_id)
