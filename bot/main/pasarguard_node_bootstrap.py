"""
PasarGuard: cloud-init marzban-node на VPS + регистрация ноды в панели (POST /node).
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional, Tuple

import paramiko
from django.conf import settings

from bot.main.PasarGuardAPI import PasarGuardAPI
from bot.models import Server

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))


def _load_node_cert_pem() -> Optional[str]:
    cert_file = (getattr(settings, "PASARGUARD_NODE_CERT_FILE", None) or "").strip()
    if not cert_file:
        return None
    path = Path(cert_file)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if "BEGIN CERTIFICATE" not in raw:
        return None
    return raw


def build_marzban_node_cloud_init(cert_pem: str) -> str:
    """Bash-скрипт: установка marzban-node + запись cert (как bot/tasks.py CLOUD_INIT_MARZBAN)."""
    cert_escaped = cert_pem.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f"""#!/bin/bash

CERT="{cert_escaped}"
DOCKER_COMPOSE_YML="services:
  marzban-node:
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host

    volumes:
      - /var/lib/marzban-node:/var/lib/marzban-node

    environment:
      SSL_CLIENT_CERT_FILE: /var/lib/marzban-node/ssl_client_cert.pem
      SERVICE_PROTOCOL: rest"
apt update
apt install git -y
apt install socat -y
apt install docker.io -y
apt install docker-compose -y

git clone https://github.com/Gozargah/Marzban-node || true

mkdir -p /var/lib/marzban-node/

echo -e "$CERT" > /var/lib/marzban-node/ssl_client_cert.pem

cd Marzban-node && rm -f docker-compose.yml && echo "$DOCKER_COMPOSE_YML" > docker-compose.yml && docker-compose down  && docker-compose up -d

echo "Script completed successfully."
"""


def _node_display_name(server: Server) -> str:
    country_label = ""
    if server.country_id and server.country:
        country_label = (server.country.name_for_app or server.country.name or "").strip()
    hosting = (server.hosting or "").strip()
    if country_label and hosting:
        return f"{country_label} {hosting}"
    return hosting or country_label or f"server-{server.pk}"


def django_ssh_looks_weak(server: Server) -> bool:
    pwd = (server.password or "").strip()
    return not pwd or pwd in _SERVER_PASSWORD_PLACEHOLDERS


def bootstrap_pasarguard_for_server(
    server: Server,
    *,
    api: Optional[PasarGuardAPI] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
    cert_pem: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    SSH cloud-init marzban-node + POST /node в PasarGuard.
    При успехе — is_pasarguard_activated=True.
    """
    def _emit(level: str, message: str) -> None:
        if log_fn:
            log_fn(level, message)

    ip = (server.ip_address or "").strip()
    if not ip:
        return False, "пустой ip_address"

    if django_ssh_looks_weak(server):
        return False, "нужен SSH пароль в Server.password"

    pem = cert_pem or _load_node_cert_pem()
    if not pem:
        return False, "PASARGUARD_NODE_CERT_FILE не задан или файл не найден"

    cloud_init = build_marzban_node_cloud_init(pem)

    _emit("DEBUG", f"SSH cloud-init marzban-node для {ip}")
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=ip,
            username=(server.user or "root").strip() or "root",
            password=server.password,
        )
        stdin, stdout, stderr = ssh_client.exec_command(cloud_init)
        stdout.read()
        stderr.read()
        exit_code = stdout.channel.recv_exit_status()
        ssh_client.close()
        if exit_code != 0:
            return False, f"cloud-init exit={exit_code}"
    except paramiko.AuthenticationException:
        return False, "SSH authentication failed"
    except paramiko.SSHException as exc:
        return False, f"SSH: {exc}"
    except Exception as exc:
        return False, f"SSH: {exc!r}\n{traceback.format_exc()}"

    panel = api or PasarGuardAPI()
    if not panel.api_token:
        return False, "нет API-токена PasarGuard"

    name = _node_display_name(server)
    ok, result = panel.add_node(ip=ip, name=name)
    if not ok:
        return False, f"add_node failed: {result!r}"

    server.is_pasarguard_activated = True
    server.save(update_fields=["is_pasarguard_activated"])
    _emit("INFO", f"Готово: {name} ({ip})")
    return True, "ok"
