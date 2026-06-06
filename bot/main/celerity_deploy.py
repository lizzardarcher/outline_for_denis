#!/usr/bin/env python3
"""
C³ CELERITY: создание ноды в панели (при необходимости) и автоматическая установка ПО (POST /nodes/:id/setup).

Политика ключей (на будущее, единая для Marzban и Celerity):
  У пользователя один активный ключ на протокол/панель. При замене ключа: сначала удаляем
  пользователя из Marzban и из Celerity (насколько применимо), затем создаём нового пользователя
  в нужной панели с тем же стабильным идентификатором (обычно Telegram user_id).

Запуск из корня проекта (где manage.py):

  Только setup (нода уже в панели):
    python3 bot/main/celerity_deploy.py --ip 185.246.118.59

  Одна нода + setup (фильтр один сервер):
    python3 bot/main/celerity_deploy.py --provision --ip 185.246.118.59
    python3 bot/main/celerity_deploy.py --provision --server-id 2822645

  Массовый --provision: сначала по очереди POST /nodes для всех без ноды,
  затем по очереди POST /nodes/:id/setup (те же фильтры, что и без --provision):
    python3 bot/main/celerity_deploy.py --provision

  Массовый только setup (ноды уже в панели), is_c3celeryty_activated=False:
    python3 bot/main/celerity_deploy.py

  Пользователь в панели (отладка / разбор ответа API для парсинга ключа):
    python3 bot/main/celerity_deploy.py --celerity-create-user --celerity-user-id 123456789
    python3 bot/main/celerity_deploy.py --celerity-delete-user --celerity-user-id 123456789
    python3 bot/main/celerity_deploy.py --celerity-get-user --celerity-user-id 123456789

Константы группы и SSH совпадают по смыслу с test_celerity_api.py (группа «Марвел», порт 443, и т.д.).
Переменные окружения: C3CELERYTY_API_ENDPOINT, C3CELERYTY_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Optional

if __name__ == "__main__":
    from pathlib import Path

    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from bot.main import django_orm  # noqa: E402  # django.setup() при импорте

from bot.main.CelerityAPI import CelerityAPI  # noqa: E402
from bot.main.hysteria_tls_meta import try_sync_hysteria_tls_meta_after_setup  # noqa: E402
from bot.models import Server  # noqa: E402
from django.conf import settings  # noqa: E402

# --- Группа серверов в панели (как test_celerity_api.py) ---
CELERITY_SERVER_GROUP_NAME = "Марвел"
CELERITY_SERVER_GROUP_ID = None  # или Mongo id строкой — без GET /groups

# --- POST /nodes ---
CELERITY_NODE_PORT = 443
CELERITY_SSH_PORT = 22
CELERITY_SSH_PRIVATE_KEY = None  # опционально PEM
CELERITY_NODE_DOMAIN = None
CELERITY_NODE_SNI = None

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))

DEFAULT_NODE_TYPE = "hysteria"
DEFAULT_SETUP_TIMEOUT = 300


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}")


def _mask_key(key: Optional[str], keep: int = 6) -> str:
    if not key:
        return "(пусто)"
    k = key.strip()
    if len(k) <= keep * 2:
        return "***"
    return f"{k[:keep]}…{k[-keep:]}"


def _server_label(s: Server) -> str:
    host = (s.hosting or "").strip() or "—"
    return f"Server pk={s.pk} ip={s.ip_address!r} hosting={host!r}"


def _flag_from_country_name_for_app(name_for_app: Optional[str]) -> str:
    """
    В Country.name_for_app хранится строка вида «Россия 🇷🇺»; флаг — в конце.
    Кодпоинты флага — пара regional indicators (два «символа» в Python), не один.
    """
    if not name_for_app:
        return ""
    s = name_for_app.rstrip()
    if not s:
        return ""
    if len(s) >= 2:
        o2, o1 = ord(s[-2]), ord(s[-1])
        if 0x1F1E6 <= o2 <= 0x1F1FF and 0x1F1E6 <= o1 <= 0x1F1FF:
            return s[-2:]
    return s[-1]


def _flag_emoji_for_server(server: Server) -> str:
    country = getattr(server, "country", None)
    if country is None:
        return ""
    return _flag_from_country_name_for_app(
        getattr(country, "name_for_app", None) or ""
    )


def _dry_run_flag_suffix(server: Server) -> str:
    emoji = _flag_emoji_for_server(server)
    if not emoji:
        return ""
    return f" country_emoji={emoji}"


def _node_body_for_log(body: dict) -> str:
    try:
        o = json.loads(json.dumps(body, default=str))
    except (TypeError, ValueError):
        return str(body)
    ssh = o.get("ssh")
    if isinstance(ssh, dict):
        if ssh.get("password"):
            ssh["password"] = "***"
        pk = ssh.get("privateKey")
        if pk:
            ssh["privateKey"] = f"<PEM, {len(pk)} символов>"
    return json.dumps(o, indent=2, ensure_ascii=False, default=str)


def _django_ssh_looks_weak(s: Server) -> bool:
    placeholders = frozenset(("", "<PASSWORD>"))
    pwd = (s.password or "").strip()
    return not pwd or pwd in placeholders


def _resolve_celerity_group_id(api: CelerityAPI) -> str:
    if CELERITY_SERVER_GROUP_ID:
        gid = str(CELERITY_SERVER_GROUP_ID).strip()
        _log(f"Группа: CELERITY_SERVER_GROUP_ID={gid!r} (имя {CELERITY_SERVER_GROUP_NAME!r})")
        return gid
    ok, data = api.list_groups()
    if not ok:
        _log(f"ОШИБКА list_groups: {data!r}")
        sys.exit(2)
    ok2, gid = api.find_group_id_by_name(CELERITY_SERVER_GROUP_NAME, groups_response=data)
    if not ok2:
        _log(f"ОШИБКА: группа {CELERITY_SERVER_GROUP_NAME!r} не найдена: {gid!r}")
        sys.exit(2)
    _log(f"Группа {CELERITY_SERVER_GROUP_NAME!r} -> id={gid!r}")
    return gid


def _build_node_payload(server: Server, group_id: str, node_type: str) -> dict:
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("У Server пустой ip_address")
    name = (server.hosting or "").strip() or f"server-{server.pk}-{ip}"

    ssh_user = (server.user or "root").strip() or "root"
    ssh_password = (server.password or "").strip()
    key_pem = (CELERITY_SSH_PRIVATE_KEY or "").strip() if CELERITY_SSH_PRIVATE_KEY else ""

    if ssh_password in _SERVER_PASSWORD_PLACEHOLDERS:
        ssh_password = ""
    if not ssh_password and not key_pem:
        raise ValueError(
            f"Нужен SSH пароль в Server.password или PEM в CELERITY_SSH_PRIVATE_KEY (pk={server.pk})"
        )

    ssh_obj: dict = {
        "port": int(CELERITY_SSH_PORT),
        "username": ssh_user,
    }
    if ssh_password:
        ssh_obj["password"] = ssh_password
    if key_pem:
        ssh_obj["privateKey"] = key_pem

    flag = _flag_emoji_for_server(server)

    body: dict = {
        "type": node_type,
        "name": name,
        "ip": ip,
        "port": int(CELERITY_NODE_PORT),
        "groups": [group_id],
        "ssh": ssh_obj,
    }
    if flag:
        body["flag"] = flag
    if CELERITY_NODE_DOMAIN:
        body["domain"] = CELERITY_NODE_DOMAIN
    if CELERITY_NODE_SNI:
        body["sni"] = CELERITY_NODE_SNI
    return body


def _create_node_or_find(
    api: CelerityAPI,
    server: Server,
    group_id: str,
    node_type: str,
    ip: str,
) -> tuple[bool, str, Any]:
    """
    POST /nodes; при «already exists» — повторный find.

    Returns:
        (ok, node_id_or_empty, error_detail)
    """
    try:
        body = _build_node_payload(server, group_id, node_type)
    except ValueError as e:
        return False, "", str(e)

    _log(f"POST /nodes (создание ноды), тело (без секретов):\n{_node_body_for_log(body)}")
    ok_c, res_c = api.create_node(body)
    if ok_c and isinstance(res_c, dict):
        nid = CelerityAPI._extract_group_id(res_c)
        if nid:
            return True, nid, None
        ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
        if ok_f:
            return True, nid2, None
        return False, "", "create OK, но нет _id в ответе и find не удался"

    err_text = res_c
    if isinstance(res_c, dict):
        err_text = res_c.get("error", res_c)
        if isinstance(err_text, str) and "already exists" in err_text.lower():
            _log("Нода с таким IP+типом уже есть, получаем id...")
            ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
            if ok_f:
                return True, nid2, None
            return False, "", f"duplicate but find failed: {nid2!r}"

    return False, "", res_c


def _build_queryset(
    include_already_c3: bool,
    server_ids: Optional[list],
    server_ips: Optional[list],
):
    qs = Server.objects.filter(is_active=True).select_related("country").order_by("id")
    if server_ids:
        qs = qs.filter(pk__in=server_ids)
    if server_ips:
        ips = [x.strip() for x in server_ips if x and str(x).strip()]
        if ips:
            qs = qs.filter(ip_address__in=ips)
    if not include_already_c3 and hasattr(Server, "is_c3celeryty_activated"):
        qs = qs.filter(is_c3celeryty_activated=False)
    return qs

def _mark_server_c3_done(server: Server) -> None:
    if hasattr(Server, "is_c3celeryty_activated"):
        try_sync_hysteria_tls_meta_after_setup(server, log_fn=lambda level, msg: _log(f"[{level}] {msg}"))
        server.is_c3celeryty_activated = True
        server.save(update_fields=["is_c3celeryty_activated"])
        _log(f"В БД выставлено is_c3celeryty_activated=True для pk={server.pk}")


def _run_provision_two_phase(
    api: CelerityAPI,
    servers: list,
    group_id: Optional[str],
    node_type: str,
    setup_timeout: int,
    dry_run: bool,
) -> tuple[int, int, int, int]:
    """
    Фаза 1: для каждого Server с IP — find; если ноды нет — POST /nodes (или DRY).
    Фаза 2: для каждого Server с IP — setup, если есть node_id (или DRY после «создания»).

    Returns:
        (ok_setup_count, skip_count, fail_create_count, fail_setup_count)
    """
    node_id_by_pk: dict[int, str] = {}
    pending_create_pks: set[int] = set()

    _log("=== Фаза 1: ноды в панели (по одной; POST /nodes если ноды ещё нет) ===")
    for server in servers:
        ip = (server.ip_address or "").strip()
        if not ip:
            continue

        if _django_ssh_looks_weak(server):
            _log(
                f"WARN: в Django пустой/заглушечный password — для provision нужен реальный SSH: "
                f"{_server_label(server)}"
            )

        ok_find, node_id = api.find_node_id_by_ip(ip, node_type)
        if ok_find:
            node_id_by_pk[server.pk] = node_id
            extra = _dry_run_flag_suffix(server) if dry_run else ""
            _log(f"Фаза 1: нода уже есть node_id={node_id!r} {_server_label(server)}{extra}")
            continue

        if dry_run:
            pending_create_pks.add(server.pk)
            _log(
                f"DRY-RUN фаза 1: создали бы ноду {node_type!r} для {_server_label(server)}"
                f"{_dry_run_flag_suffix(server)}"
            )
            continue

        assert group_id is not None
        ok_c, nid, err_c = _create_node_or_find(api, server, group_id, node_type, ip)
        if not ok_c:
            _log(f"FAIL фаза 1 (create_node): {_server_label(server)} — {err_c!r}")
            continue
        node_id_by_pk[server.pk] = nid
        _log(f"Фаза 1 OK: node_id={nid!r} {_server_label(server)}")

    ok_n = skip_n = fail_setup_n = 0
    fail_create_n = 0
    for server in servers:
        ip = (server.ip_address or "").strip()
        if not ip:
            continue
        if server.pk in node_id_by_pk or server.pk in pending_create_pks:
            continue
        if not dry_run:
            fail_create_n += 1

    _log("=== Фаза 2: установка ПО (POST .../setup по одной ноде) ===")
    for server in servers:
        ip = (server.ip_address or "").strip()
        if not ip:
            _log(f"SKIP (нет IP): {_server_label(server)}")
            skip_n += 1
            continue

        nid = node_id_by_pk.get(server.pk)
        if not nid and dry_run and server.pk in pending_create_pks:
            _log(
                f"DRY-RUN фаза 2: setup для {_server_label(server)} "
                f"(нода появилась бы после фазы 1){_dry_run_flag_suffix(server)}"
            )
            ok_n += 1
            continue

        if not nid:
            _log(
                f"SKIP фаза 2 (нет node_id — ошибка или пропуск на фазе 1): "
                f"{_server_label(server)}"
            )
            skip_n += 1
            continue

        if dry_run:
            _log(
                f"DRY-RUN фаза 2: setup node_id={nid!r} {_server_label(server)}"
                f"{_dry_run_flag_suffix(server)}"
            )
            ok_n += 1
            continue

        _log(f"SETUP (до {setup_timeout}s): node_id={nid!r} {_server_label(server)}")
        ok_setup, data = api.setup_node(nid, request_timeout=setup_timeout)
        if ok_setup:
            _log(f"OK: {_server_label(server)}")
            if isinstance(data, dict) and data.get("logs"):
                print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:4000])
            _mark_server_c3_done(server)
            ok_n += 1
        else:
            _log(f"FAIL setup: {_server_label(server)} — {data!r}")
            fail_setup_n += 1

    return ok_n, skip_n, fail_create_n, fail_setup_n


def _require_celerity_user_id(args: argparse.Namespace) -> str:
    raw = getattr(args, "celerity_user_id", None)
    uid = (raw if raw is not None else "").strip()
    if not uid:
        _log("ОШИБКА: укажите --celerity-user-id (обычно Telegram user_id, как в Marzban username)")
        sys.exit(2)
    return uid


def _run_celerity_user_cli(api: CelerityAPI, args: argparse.Namespace) -> None:
    """Один из режимов --celerity-*-user; завершает процесс через sys.exit."""
    uid = _require_celerity_user_id(args)
    display_name = (args.celerity_display_name or "").strip() or uid

    if args.celerity_get_user:
        _log(f"GET /users/{uid!r}")
        ok, data = api.get_user(uid)
        if not ok:
            _log(f"ОШИБКА get_user: {data!r}")
            sys.exit(1)
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        if isinstance(data, dict) and data.get("subscriptionToken"):
            tok = str(data["subscriptionToken"])
            _log("GET /files/info/:token (публичный маршрут, без X-API-Key)")
            ok_i, info = api.get_subscription_info(tok)
            if ok_i:
                print("\n--- subscription info (GET /files/info/:token) ---")
                print(json.dumps(info, indent=2, ensure_ascii=False, default=str))
            else:
                _log(
                    f"WARN: /files/info не удался: {info!r} "
                    "(на пустом nodes[] у пользователя панель часто отдаёт 404 — см. ниже GET /files/:token)"
                )

            _log("GET /files/:token?format=uri — список URI подписки (для парсинга ключа)")
            ok_f, sub = api.get_subscription_content(tok, params={"format": "uri"})
            if ok_f:
                print("\n--- subscription content (GET /files/:token?format=uri) ---")
                if isinstance(sub, str):
                    body = sub.strip()
                    lim = 12000
                    if len(body) > lim:
                        print(body[:lim] + "\n… [обрезано, всего символов: %d]" % len(body))
                    else:
                        print(body if body else "(пусто — проверьте ноды в группе пользователя)")
                else:
                    print(json.dumps(sub, indent=2, ensure_ascii=False, default=str))
            else:
                _log(f"WARN: GET /files/:token не удался: {sub!r}")
        sys.exit(0)

    if args.celerity_delete_user:
        if args.dry_run:
            _log(f"DRY-RUN: DELETE /users/{uid!r}")
            sys.exit(0)
        _log(f"DELETE /users/{uid!r}")
        ok, data = api.delete_user(uid)
        if ok:
            _log("OK: пользователь удалён (или ответ 204)")
            sys.exit(0)
        err_txt = data
        if isinstance(data, dict):
            err_txt = data.get("error", data)
        low = str(err_txt).lower()
        if "not found" in low or "404" in low:
            _log(f"WARN: пользователь не найден (возможно уже удалён): {data!r}")
            sys.exit(0)
        _log(f"ОШИБКА delete_user: {data!r}")
        sys.exit(1)

    if args.celerity_create_user:
        if args.dry_run:
            body = {
                "userId": uid,
                "username": display_name,
                "enabled": True,
                "groups": [
                    f"<ObjectId группы «{CELERITY_SERVER_GROUP_NAME}» — реальный id подставляется после GET /groups>"
                ],
            }
            _log("DRY-RUN: POST /users (тело без запросов к панели)")
            print(json.dumps(body, indent=2, ensure_ascii=False))
            sys.exit(0)
        group_id = _resolve_celerity_group_id(api)
        body = {
            "userId": uid,
            "username": display_name,
            "enabled": True,
            "groups": [group_id],
        }
        _log(f"POST /users userId={uid!r} username={display_name!r}")
        ok, data = api.create_user(body)
        if not ok:
            _log(f"ОШИБКА create_user: {data!r}")
            sys.exit(1)
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        _log("OK: create_user")
        sys.exit(0)

    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="C³ CELERITY: provision (опц.) + setup нод для Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  Массовый provision: все ноды создаются по очереди, затем по очереди setup:
    python3 bot/main/celerity_deploy.py --provision

  Один сервер (provision + setup):
    python3 bot/main/celerity_deploy.py --provision --ip 185.246.118.59

  Разбор ответа API пользователя (ключ/subscription):
    python3 bot/main/celerity_deploy.py --celerity-get-user --celerity-user-id 123456789
""",
    )
    parser.add_argument(
        "--provision",
        action="store_true",
        help=(
            "Две фазы: сначала для каждого сервера в выборке — POST /nodes если ноды нет в панели, "
            "затем для каждого — POST /nodes/:id/setup. Шаги выполняются по одному, в порядке выборки. "
            "Без --ip/--server-id обрабатываются все подходящие Server (как без --provision)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не вызывать create/setup нод; для --celerity-create-user/--celerity-delete-user — без POST/DELETE в панель.",
    )
    parser.add_argument(
        "--include-already-c3",
        action="store_true",
        help="Не фильтровать по is_c3celeryty_activated (по умолчанию только False).",
    )
    parser.add_argument(
        "--ip",
        action="append",
        dest="server_ips",
        default=None,
        metavar="ADDR",
        help="Фильтр Server.ip_address в Django",
    )
    parser.add_argument(
        "--server-id",
        type=int,
        action="append",
        dest="server_ids",
        metavar="ID",
        help="Фильтр Server.id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Не более N серверов после сортировки (0 = все)",
    )
    parser.add_argument(
        "--node-type",
        default=DEFAULT_NODE_TYPE,
        choices=("hysteria", "xray"),
        help="Тип ноды в панели",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_SETUP_TIMEOUT,
        metavar="SEC",
        help="HTTP timeout для POST /setup",
    )
    user_grp = parser.add_mutually_exclusive_group()
    user_grp.add_argument(
        "--celerity-create-user",
        action="store_true",
        help="POST /users в Celerity (нужен --celerity-user-id; группа — как у нод, см. константы).",
    )
    user_grp.add_argument(
        "--celerity-delete-user",
        action="store_true",
        help="DELETE /users/:userId в Celerity.",
    )
    user_grp.add_argument(
        "--celerity-get-user",
        action="store_true",
        help="GET /users/:userId — полный JSON в stdout; при наличии subscriptionToken дополнительно GET /files/info.",
    )
    parser.add_argument(
        "--celerity-user-id",
        default=None,
        metavar="ID",
        help="Идентификатор userId в панели Celerity (как правило str(TelegramUser.user_id)).",
    )
    parser.add_argument(
        "--celerity-display-name",
        default=None,
        metavar="NAME",
        help="Поле username при POST /users (по умолчанию совпадает с --celerity-user-id).",
    )
    args = parser.parse_args()

    endpoint = getattr(settings, "C3CELERYTY_API_ENDPOINT", None) or ""
    key = getattr(settings, "C3CELERYTY_API_KEY", None) or ""
    _log(f"C3CELERYTY_API_ENDPOINT: {endpoint or '(не задан)'}")
    _log(f"C3CELERYTY_API_KEY:      {_mask_key(key)}")
    if not endpoint.strip() or not (key or "").strip():
        _log("ОШИБКА: задайте C3CELERYTY_API_ENDPOINT и C3CELERYTY_API_KEY")
        sys.exit(2)

    api = CelerityAPI()

    user_mode = bool(
        args.celerity_create_user or args.celerity_delete_user or args.celerity_get_user
    )
    if user_mode and args.provision:
        _log("ОШИБКА: нельзя совмещать --provision с --celerity-create-user / --celerity-delete-user / --celerity-get-user")
        sys.exit(2)
    if user_mode:
        _run_celerity_user_cli(api, args)

    if args.limit < 0:
        _log("ОШИБКА: --limit не может быть отрицательным")
        sys.exit(2)

    qs = _build_queryset(args.include_already_c3, args.server_ids, args.server_ips)
    if args.limit and args.limit > 0:
        qs = qs[: args.limit]

    servers = list(qs)
    _log(f"К обработке серверов: {len(servers)} (dry_run={args.dry_run}, provision={args.provision})")

    if not servers:
        _log(
            "Нет записей Server по фильтрам (is_active, is_c3celeryty_activated, --ip, --server-id)."
        )

    if args.provision:
        group_id: Optional[str] = None
        if not args.dry_run:
            group_id = _resolve_celerity_group_id(api)
        else:
            _log(
                "DRY-RUN: была бы загрузка группы (GET /groups); фаза 1 — POST /nodes только там, "
                "где ноды ещё нет"
            )
        ok_n, skip_n, fail_create_n, fail_setup_n = _run_provision_two_phase(
            api,
            servers,
            group_id,
            args.node_type,
            args.timeout,
            args.dry_run,
        )
        _log(
            f"Итого: ok_setup={ok_n} skip={skip_n} "
            f"fail_create={fail_create_n} fail_setup={fail_setup_n}"
        )
        sys.exit(1 if (fail_create_n or fail_setup_n) else 0)

    ok_n = skip_n = fail_n = 0

    for server in servers:
        ip = (server.ip_address or "").strip()
        if not ip:
            _log(f"SKIP (нет IP): {_server_label(server)}")
            skip_n += 1
            continue

        ok_find, node_id = api.find_node_id_by_ip(ip, args.node_type)

        if not ok_find:
            _log(
                f"SKIP (нет ноды {args.node_type!r} в панели): {_server_label(server)} — {node_id!r}"
            )
            skip_n += 1
            continue

        if args.dry_run:
            _log(
                f"DRY-RUN setup: node_id={node_id!r} {_server_label(server)}"
                f"{_dry_run_flag_suffix(server)}"
            )
            ok_n += 1
            continue

        _log(f"SETUP (до {args.timeout}s): node_id={node_id!r} {_server_label(server)}")
        ok_setup, data = api.setup_node(node_id, request_timeout=args.timeout)
        if ok_setup:
            _log(f"OK: {_server_label(server)}")
            if isinstance(data, dict) and data.get("logs"):
                print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:4000])
            _mark_server_c3_done(server)
            ok_n += 1
        else:
            _log(f"FAIL setup: {_server_label(server)} — {data!r}")
            fail_n += 1

    _log(f"Итого: ok={ok_n} skip={skip_n} fail={fail_n}")
    sys.exit(1 if fail_n else 0)


if __name__ == "__main__":
    main()
