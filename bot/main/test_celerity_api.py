#!/usr/bin/env python3
"""
Интеграционная проверка CelerityAPI против панели C³ CELERITY.

Запуск из корня проекта (где manage.py), с тем же Python/venv, что и у Django:

    python3 bot/main/test_celerity_api.py

Переменные окружения: C3CELERYTY_API_ENDPOINT, C3CELERYTY_API_KEY (как в Django).

Режимы:
  без флагов — только чтение (GET /stats, /nodes, /users, get_user);
  --create-user / --delete-user / --add-node — одно действие (взаимоисключающие);
  для --create-user и --add-node в тело запроса добавляется groups: [<id>] (группа CELERITY_SERVER_GROUP_NAME);
  для --add-node в тело добавляется ssh (username из Server.user, password из Server.password, порт CELERITY_SSH_PORT).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any


# Корень проекта должен быть в PYTHONPATH; при запуске как файл — добавляем родителя bot/main
if __name__ == "__main__":
    from pathlib import Path

    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from bot.main import django_orm  # noqa: E402  # isort: skip — django.setup() при импорте

from bot.main.CelerityAPI import CelerityAPI  # noqa: E402
from bot.models import Server, TelegramUser  # noqa: E402
from django.conf import settings  # noqa: E402

# --- Тестовые сущности Django ---
TEST_USERNAME = "megafoll"
TEST_SERVER_PK = 2822655

# --- Группа серверов C³ CELERITY (как в панели) ---
CELERITY_SERVER_GROUP_NAME = "Марвел"
# Если известен Mongo ObjectId группы — можно задать и не дергать GET /groups:
CELERITY_SERVER_GROUP_ID = None  # например "674a1b2c3d4e5f6789abcdef"

# --- Тело POST /nodes при --add-node (дополняется ip/name из Server) ---
CELERITY_NODE_TYPE = "hysteria"
CELERITY_NODE_PORT = 443
# SSH для панели (автонастройка, терминал в UI): см. поля ssh в CELERITY hyNodeModel
CELERITY_SSH_PORT = 22
# Опционально: PEM приватного ключа вместо пароля (если задан — уходит в ssh.privateKey)
CELERITY_SSH_PRIVATE_KEY = None
# Необязательно: домен/SNI панели; оставьте None — поле не попадёт в JSON
CELERITY_NODE_DOMAIN = None
CELERITY_NODE_SNI = None

# Пустой пароль или заводская заглушка модели Server — не считаем за SSH-кредит
_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {_ts()}  {title}\n{line}")


def _node_body_for_log(body: dict) -> str:
    """Копия тела POST /nodes для лога без секретов."""
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


def _mask_key(key: str | None, keep: int = 6) -> str:
    if not key:
        return "(пусто)"
    k = key.strip()
    if len(k) <= keep * 2:
        return "***"
    return f"{k[:keep]}…{k[-keep:]}"


def _dump(label: str, ok: bool, payload: Any, max_depth_list: int = 50) -> None:
    print(f"\n--- {label} ---")
    print(f"success: {ok}")
    if isinstance(payload, list) and len(payload) > max_depth_list:
        print(f"(список из {len(payload)} элементов, показываем первые {max_depth_list})")
        payload = payload[:max_depth_list]
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    elif payload is None:
        print("(нет тела ответа)")
    else:
        print(payload)


def _load_context():
    _banner("Контекст Django")
    endpoint = getattr(settings, "C3CELERYTY_API_ENDPOINT", None) or ""
    key = getattr(settings, "C3CELERYTY_API_KEY", None) or ""
    print(f"C3CELERYTY_API_ENDPOINT: {endpoint or '(не задан)'}")
    print(f"C3CELERYTY_API_KEY:      {_mask_key(key)}")

    user = TelegramUser.objects.filter(username__iexact=TEST_USERNAME).first()
    if not user:
        print(f"\nОШИБКА: TelegramUser с username={TEST_USERNAME!r} не найден.")
        sys.exit(1)
    print(f"\nTelegramUser: pk={user.pk} user_id={user.user_id} username={user.username!r}")

    try:
        server = Server.objects.select_related("country").get(pk=TEST_SERVER_PK)
    except Server.DoesNotExist:
        print(f"\nОШИБКА: Server id={TEST_SERVER_PK} не найден.")
        sys.exit(1)

    c3_flag = getattr(server, "is_c3celeryty_activated", None)
    cname = None
    if server.country_id:
        cname = server.country.name_for_app or server.country.name
    print(
        f"Server: pk={server.pk} ip={server.ip_address!r} hosting={server.hosting!r} "
        f"country={cname!r}"
    )
    if c3_flag is not None:
        print(f"         is_c3celeryty_activated={c3_flag}")

    return user, server


def _resolve_celerity_group_id(api: CelerityAPI) -> str:
    """ObjectId группы для поля groups при создании user/node."""
    if CELERITY_SERVER_GROUP_ID:
        gid = str(CELERITY_SERVER_GROUP_ID).strip()
        print(f"Группа: id из CELERITY_SERVER_GROUP_ID={gid!r} (имя в панели: {CELERITY_SERVER_GROUP_NAME!r})")
        return gid
    _banner("GET /groups (поиск группы)")
    ok, data = api.list_groups()
    _dump("groups", ok, data)
    if not ok:
        print(f"\nОШИБКА: list_groups не удался: {data!r}")
        sys.exit(1)
    ok2, gid = api.find_group_id_by_name(CELERITY_SERVER_GROUP_NAME, groups_response=data)
    if not ok2:
        print(f"\nОШИБКА: не удалось найти группу {CELERITY_SERVER_GROUP_NAME!r}: {gid!r}")
        sys.exit(1)
    print(f"\nГруппа: {CELERITY_SERVER_GROUP_NAME!r} -> id={gid!r}")
    return gid


def _build_node_payload(server: Server, group_id: str) -> dict:
    ip = (server.ip_address or "").strip()
    if not ip:
        print("ОШИБКА: у Server пустой ip_address — ноду добавить нельзя.")
        sys.exit(1)
    name = (server.hosting or "").strip() or f"server-{server.pk}-{ip}"

    ssh_user = (server.user or "root").strip() or "root"
    ssh_password = (server.password or "").strip()
    key_pem = (CELERITY_SSH_PRIVATE_KEY or "").strip() if CELERITY_SSH_PRIVATE_KEY else ""

    if ssh_password in _SERVER_PASSWORD_PLACEHOLDERS:
        ssh_password = ""
    if not ssh_password and not key_pem:
        print(
            "ОШИБКА: для SSH в панели нужен пароль или ключ.\n"
            "  • Укажите реальный SSH-пароль в Django: Server.password (запись "
            f"id={TEST_SERVER_PK}).\n"
            "  • Либо задайте PEM в константе CELERITY_SSH_PRIVATE_KEY в этом скрипте."
        )
        sys.exit(1)

    ssh_obj: dict = {
        "port": int(CELERITY_SSH_PORT),
        "username": ssh_user,
    }
    if ssh_password:
        ssh_obj["password"] = ssh_password
    if key_pem:
        ssh_obj["privateKey"] = key_pem

    body: dict = {
        "type": CELERITY_NODE_TYPE,
        "name": name,
        "ip": ip,
        "port": int(CELERITY_NODE_PORT),
        "groups": [group_id],
        "ssh": ssh_obj,
    }
    if CELERITY_NODE_DOMAIN:
        body["domain"] = CELERITY_NODE_DOMAIN
    if CELERITY_NODE_SNI:
        body["sni"] = CELERITY_NODE_SNI
    return body


def _run_read_only_suite(api: CelerityAPI, user: TelegramUser, server: Server) -> None:
    _banner("GET /stats")
    ok, data = api.get_stats()
    _dump("stats", ok, data)

    _banner("GET /nodes")
    ok, data = api.list_nodes()
    _dump("nodes", ok, data)
    if ok and isinstance(data, list):
        ip = (server.ip_address or "").strip()
        if ip:
            matches = []
            for n in data:
                if not isinstance(n, dict):
                    continue
                nip = str(n.get("ip") or "").strip()
                if nip == ip:
                    matches.append(n)
            print(f"\nНоды с IP как у Server #{server.pk} ({ip}): {len(matches)} шт.")
            if matches:
                print(json.dumps(matches, indent=2, ensure_ascii=False, default=str))

    _banner("GET /users (первые записи)")
    ok, data = api.list_users()
    _dump("users (raw)", ok, data)
    if ok and isinstance(data, dict) and "users" in data:
        _dump("users['users']", True, data.get("users"))
    elif ok and isinstance(data, dict) and "data" in data:
        _dump("users['data']", True, data.get("data"))

    celerity_user_id = str(user.user_id)
    _banner(f"GET /users/{celerity_user_id}")
    ok, data = api.get_user(celerity_user_id)
    _dump(f"user {celerity_user_id}", ok, data)
    if ok and isinstance(data, dict):
        token = data.get("subscriptionToken")
        if token:
            print(f"\nsubscriptionToken: {token!r}")
            _banner("GET /files/info/:token")
            ok2, info = api.get_subscription_info(str(token))
            _dump("subscription info", ok2, info)


def main() -> None:
    parser = argparse.ArgumentParser(description="Тест CelerityAPI (C³ CELERITY)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--create-user",
        action="store_true",
        help="POST /users — userId из TelegramUser.user_id, username из TEST_USERNAME",
    )
    action.add_argument(
        "--delete-user",
        action="store_true",
        help="DELETE /users/:userId — userId = TelegramUser.user_id",
    )
    action.add_argument(
        "--add-node",
        action="store_true",
        help="POST /nodes — Server + группа + ssh (password из Server.password или CELERITY_SSH_PRIVATE_KEY)",
    )
    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="POST /sync — все ноды (после основного сценария: только в режиме без --create/--delete/--add)",
    )
    args = parser.parse_args()

    user, server = _load_context()
    api = CelerityAPI()
    celerity_user_id = str(user.user_id)

    if args.create_user:
        group_id = _resolve_celerity_group_id(api)
        _banner("POST /users (create_user)")
        body = {
            "userId": celerity_user_id,
            "username": user.username or celerity_user_id,
            "enabled": True,
            "groups": [group_id],
        }
        print("Тело запроса (TelegramUser + группа серверов):")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        ok, data = api.create_user(body)
        _dump("create_user", ok, data)
    elif args.delete_user:
        _banner(f"DELETE /users/{celerity_user_id}")
        print(f"userId: {celerity_user_id!r} (из TelegramUser username={TEST_USERNAME!r})")
        ok, data = api.delete_user(celerity_user_id)
        _dump("delete_user", ok, data)
    elif args.add_node:
        group_id = _resolve_celerity_group_id(api)
        _banner("POST /nodes (create_node)")
        body = _build_node_payload(server, group_id)
        print("Тело запроса (CELERITY_* + Server + группа + ssh), секреты замаскированы:")
        print(_node_body_for_log(body))
        ok, data = api.create_node(body)
        _dump("create_node", ok, data)
    else:
        _run_read_only_suite(api, user, server)
        if args.sync_all:
            _banner("POST /sync")
            ok, data = api.sync_all()
            _dump("sync_all", ok, data)

    _banner("Готово")
    print("Проверка завершена.\n")

if __name__ == "__main__":
    main()
