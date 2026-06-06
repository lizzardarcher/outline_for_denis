"""
Выдача Hysteria2 (C³ CELERITY): ротация пользователя в панели и извлечение TLS-URI из подписки.

Политика: перед созданием нового ключа — удаление пользователя в Marzban и в Celerity,
затем POST /users в Celerity (как на сайте для других протоколов).

Подписка Celerity отдаёт hopping + insecure=1; для Happ (sing-box/Xray ≥1.13) URI
переписывается: pinSHA256 и SNI с /etc/hysteria/cert.pem, insecure убирается.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings

from bot.main.CelerityAPI import CelerityAPI
from bot.main.MarzbanAPI import MarzbanAPI
from bot.models import Server


def try_delete_celerity_user(telegram_user_id) -> None:
    """DELETE /users в Celerity; сетевые/прочие ошибки не пробрасываются (как на сайте)."""
    try:
        CelerityAPI().delete_user(str(telegram_user_id))
    except Exception:
        pass


def _celerity_group_id(api: CelerityAPI) -> str:
    gid_env = getattr(settings, "CELERITY_SERVER_GROUP_ID", None)
    if gid_env:
        return str(gid_env).strip()
    name = getattr(settings, "CELERITY_SERVER_GROUP_NAME", None) or "Марвел"
    ok, data = api.list_groups()
    if not ok:
        raise RuntimeError(f"Celerity list_groups: {data!r}")
    ok2, gid = api.find_group_id_by_name(name, groups_response=data)
    if not ok2:
        raise RuntimeError(f"Celerity: группа «{name}» не найдена: {gid!r}")
    return gid


def sanitize_hysteria2_uri_for_happ(
    uri: str,
    *,
    sni: str,
    pin_sha256: str,
) -> str:
    """
    Убирает insecure/allowInsecure, подставляет sni и pinSHA256 (hex uppercase).
    Сохраняет mport, alpn, obfs и прочие параметры Celerity.
    """
    pin = (pin_sha256 or "").replace(":", "").strip().upper()
    sni_val = (sni or "").strip()
    if not pin or not sni_val:
        raise ValueError("sni и pin_sha256 обязательны для sanitize_hysteria2_uri_for_happ")

    parsed = urlparse(uri)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("insecure", None)
    query.pop("allowInsecure", None)
    query["sni"] = sni_val
    query["pinSHA256"] = pin
    if "alpn" not in query:
        query["alpn"] = "h3"

    return urlunparse(parsed._replace(query=urlencode(query)))


def pick_hysteria2_tls_uri(subscription_text: str, server_ip: str) -> Optional[str]:
    """
    Из многострочного ответа GET /files/:token?format=uri — строка hysteria2:// для server_ip
    без port hopping (без query-параметра mport=).
    """
    ip = (server_ip or "").strip()
    if not ip:
        return None
    for raw in subscription_text.splitlines():
        line = raw.strip()
        if not line or "hysteria2://" not in line:
            continue
        if ip not in line:
            continue
        if "mport=" in line.lower():
            continue
        return line
    return None


def pick_hysteria2_hopping_uri(subscription_text: str, server_ip: str) -> Optional[str]:
    """
    Ищет строку с hysteria2:// для server_ip, у которой есть параметр mport
    (port hopping), и возвращает эту строку целиком.
    """
    ip = (server_ip or "").strip()
    if not ip:
        return None

    for raw in subscription_text.splitlines():
        line = raw.strip()
        if not line or "hysteria2://" not in line:
            continue
        if ip not in line:
            continue
        if "mport=" not in line.lower():
            continue
        return line

    return None


def _server_for_hysteria_issue(server_ip: str) -> Optional[Server]:
    ip = (server_ip or "").strip()
    if not ip:
        return None
    return (
        Server.objects.filter(
            ip_address=ip,
            is_c3celeryty_activated=True,
        )
        .order_by("pk")
        .first()
    )



def issue_hysteria2_tls_for_user(
    *,
    telegram_user_id: int,
    display_username: str,
    server_ip: str,
) -> Tuple[bool, Any]:
    """
    Удаляет пользователя в Marzban и Celerity, создаёт в Celerity, отдаёт одну hopping-ссылку
    с pinSHA256/SNI для Happ (без insecure=1).

    Returns:
        (True, uri: str) или (False, сообщение_об_ошибке)
    """
    uid = str(int(telegram_user_id))
    api = CelerityAPI()
    try:
        MarzbanAPI().delete_user(uid)
    except Exception:
        pass
    ok_del, _ = api.delete_user(uid)
    if not ok_del:
        pass

    try:
        gid = _celerity_group_id(api)
    except RuntimeError as e:
        return False, str(e)

    body = {
        "userId": uid,
        "username": (display_username or uid).strip(),
        "enabled": True,
        "groups": [gid],
    }
    ok_c, res_c = api.create_user(body)
    if not ok_c:
        return False, f"Celerity create_user: {res_c!r}"

    ok_g, data_g = api.get_user(uid)
    if not ok_g or not isinstance(data_g, dict):
        return False, f"Celerity get_user: {data_g!r}"

    tok = data_g.get("subscriptionToken")
    if not tok:
        return False, "В ответе get_user нет subscriptionToken"

    ok_s, sub = api.get_subscription_content(str(tok), params={"format": "uri"})
    if not ok_s:
        return False, f"Celerity subscription: {sub!r}"
    if not isinstance(sub, str) or not sub.strip():
        return False, "Пустой ответ подписки (?format=uri)"

    uri = pick_hysteria2_tls_uri(sub, server_ip)
    if not uri:
        uri = pick_hysteria2_hopping_uri(sub, server_ip)
    if not uri:
        return False, (
            f"Не найдена строка hysteria2:// для IP {server_ip!r} в подписке. "
        )

    server = _server_for_hysteria_issue(server_ip)
    if not server or not server.hysteria_pin_sha256 or not server.hysteria_tls_sni:
        return False, (
            f"Нода {server_ip}: нет hysteria TLS pin/SNI в БД. "
        )

    try:
        uri = sanitize_hysteria2_uri_for_happ(
            uri,
            sni=server.hysteria_tls_sni,
            pin_sha256=server.hysteria_pin_sha256,
        )
    except ValueError as e:
        return False, str(e)

    return True, uri
