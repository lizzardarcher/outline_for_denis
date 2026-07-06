#!/usr/bin/env python3
"""
Интеграционная проверка PasarGuardAPI против панели PasarGuard.

Запуск из корня проекта (где manage.py):

    python3 bot/main/test_pasarguard_api.py

Переменные окружения: PASARGUARD_API, PASARGUARD_ADMIN_USERNAME, PASARGUARD_ADMIN_PASSWORD.

Режимы:
  без флагов — token + GET /nodes;
  --create-user / --delete-user / --get-user — действия с пользователем;
  --add-node — POST /node для Server по --server-id или --server-pk.
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

from bot.main import django_orm  # noqa: E402  # isort: skip

from bot.main.PasarGuardAPI import PasarGuardAPI  # noqa: E402
from bot.models import Server  # noqa: E402
from django.conf import settings  # noqa: E402


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {_ts()}  {title}\n{line}")


def _dump(label: str, ok: bool, payload: Any) -> None:
    print(f"\n--- {label} ---")
    print(f"success: {ok}")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    elif payload is None:
        print("(нет тела ответа)")
    else:
        print(payload)


def _node_display_name(server: Server) -> str:
    country_label = ""
    if server.country_id and server.country:
        country_label = (server.country.name_for_app or server.country.name or "").strip()
    hosting = (server.hosting or "").strip()
    if country_label and hosting:
        return f"{country_label} {hosting}"
    return hosting or country_label or f"server-{server.pk}"


def _run_read_only(api: PasarGuardAPI) -> None:
    _banner("PasarGuard read-only")
    api_url = getattr(settings, "PASARGUARD_API", None) or ""
    print(f"PASARGUARD_API = {api_url!r}")
    print(f"token: {'OK' if api.api_token else 'FAIL'}")

    ok, nodes = api.list_nodes()
    _dump("GET /nodes", ok, nodes)

    ok, users = api.list_users()
    _dump("GET /users (first page)", ok, users if not isinstance(users, list) else users[:5])


def main() -> int:
    parser = argparse.ArgumentParser(description="Тест PasarGuardAPI")
    parser.add_argument("--create-user", action="store_true")
    parser.add_argument("--delete-user", action="store_true")
    parser.add_argument("--get-user", action="store_true")
    parser.add_argument("--add-node", action="store_true")
    parser.add_argument("--user-id", default="999999001", help="Telegram user_id для теста")
    parser.add_argument(
        "--protocol",
        default="vless",
        choices=("vless", "outline"),
        help="Протокол для --create-user",
    )
    parser.add_argument("--server-id", type=int, dest="server_pk", help="Server.pk для --add-node")
    args = parser.parse_args()

    api = PasarGuardAPI()
    if not api.api_token:
        print("ОШИБКА: нет токена. Проверьте PASARGUARD_API / PASARGUARD_ADMIN_USERNAME / PASARGUARD_ADMIN_PASSWORD")
        return 2

    if args.create_user:
        uid = str(args.user_id)
        api.delete_user(uid)
        ok, res = api.create_user(username=uid, protocol=args.protocol)
        _dump(f"POST /user ({args.protocol})", ok, res)
        if ok:
            ok2, data = api.get_user(uid)
            _dump("GET /user", ok2, data)
        return 0 if ok else 1

    if args.delete_user:
        ok, res = api.delete_user(str(args.user_id))
        _dump("DELETE /user", ok, res)
        return 0 if ok else 1

    if args.get_user:
        ok, res = api.get_user(str(args.user_id))
        _dump("GET /user", ok, res)
        return 0 if ok else 1

    if args.add_node:
        if not args.server_pk:
            print("ОШИБКА: для --add-node укажите --server-id")
            return 2
        server = Server.objects.filter(pk=args.server_pk).select_related("country").first()
        if not server:
            print(f"ОШИБКА: Server pk={args.server_pk} не найден")
            return 2
        ip = (server.ip_address or "").strip()
        name = _node_display_name(server)
        ok, res = api.add_node(ip=ip, name=name)
        _dump("POST /node", ok, res)
        return 0 if ok else 1

    _run_read_only(api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
