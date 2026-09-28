"""
Установка marzban-node на VPS и регистрация ноды в панели Marzban.

Скрипт повторяет результат официального
``marzban-node.sh install`` (REST, порты 62050/62051, cert.pem),
без интерактивных вопросов и без ``logs -f``, который не завершается.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Callable, Optional, Tuple

import paramiko
from django.conf import settings

from bot.main.MarzbanAPI import MarzbanAPI
from bot.models import Server

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))
_CERT_MARKERS = ("-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----")

# Тот же client certificate, что раньше лежал в CLOUD_INIT_MARZBAN.
# Актуальный сертификат панели перекрывает его через MARZBAN_NODE_CERT_FILE.
_LEGACY_CLIENT_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIEnDCCAoQCAQAwDQYJKoZIhvcNAQENBQAwEzERMA8GA1UEAwwIR296YXJnYWgw
IBcNMjYwNTE5MDg1NTE0WhgPMjEyNjA0MjUwODU1MTRaMBMxETAPBgNVBAMMCEdv
emFyZ2FoMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEArflKFFIAufDf
k3+HqTlteUwiBaJpalvsX0WwUHsXL/hUD+FVhosAUV6CU+v7jmMDr8i4YmsobCAC
eNlR28fCBZikYkVhiJEHhxzd5uQQDZ/AsKYTnvvHYPncGIIU8D0G/ll3iqgYOtmM
Jdj+YG5a28VbQMsTmK3zcYZTLg9Qo939YIzlPIhWQ3endHOX2FfBlfEuH2+hIyI+
o8QwUrcVPD4LEqM/9wIS1pzo21xEDU9MzjCJ6A1ooyp/SfAkX2Smsf28lE6o9ZWn
AxpP6gn1eArI1ck58jj5YfgV2FYZ9DQjn45BtbACxcI7QRTTu3rLiwLFjRZ9f9AN
oJaAltUf5EaeI43wBqeAPcixQzS5RADZPVA4cvLm1Yd0IrHyekNQYDJY2FhajTeq
RSnZ0xoZ92snmOBhaxdGSLthOw4hm3T3RSvGEdpJrMRv+xZtzk5JKyyyr44sqgQ9
h6AaJ3c9AojJyX8meuHabi6lea6zwRIs8/wQBuUqeif/+seWKDXa2BB5garI5GYr
6RxgTPFrkcm10KZrTlr4bJ/hhUI1Ya1eA4IjxH1fAfixDlI7AczrkpyDfaYggBnc
zOwQYVT/mAAXEtE/p35C/dVJqB18eP//LT1GiEKniIO9UoQwy17XLJWSSAzESeSK
YWQ/rn8RBK7X/gdYNib1OZn5TfqT8OsCAwEAATANBgkqhkiG9w0BAQ0FAAOCAgEA
hKn5aO/hCz5RtvQfiDMx9Rq/a/VcuPVZv8CREXinceVKZalCtD7pkE9Y2spHxb0E
JU6HLfGNabblJbAdW0r205ejShHm5yOKIfzO7p6Qwfwd+XFLdPoKK5jUEr5qwG74
vyLjfzUiS0cIbvc7x5Sb3aR7HyEV2XHDiTrXi0fA43ntQXIZ9nU9hk3MVVLm3R6j
OvPsrirE3Sm0C0GbxSg7YAE+XfqHuxc4fZUkAhmCFVdE+8734uYdRx4f9iHxvuRN
+n1hO2/7ulDK4VJ31om9p7pbTdp56an6VxxHRg18nEWriGGbVRlF+F+OjTWeBsj1
FXgXPrZPq+mkNIf3p3PKNZfwoKKRdAD/9kq0cJn7w3rb2AP14x+z9qYBX3TzGaCf
z+Eb4MWweD/pyZ8SbUwNRZsLGtpbyFQN3Y76r/YOA4+lX8N0mr9indnNg8XQfFCW
J6TTcxwiIy+NK8XVGSoKVvXd1lqFFL78gG0jYtwLFy0IV5L4goe9fFBqXTsNaPR+
j/zpFFE2Wjosp0ozlFMScOeuPambFvVWO80F/MuQumg7YIu3VK8m/wAbWiwIENM+
JO/xsMuIlDhFezZ6jwAebAHWX5pmdAk/9hraniiCQUiRwGIwYhNP4if0jYgG7YzK
0e4u1GLX14U000cBXY3truvC0PkPqD0E1/nxWwwBlM0=
-----END CERTIFICATE-----
"""


def _valid_cert_pem(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if _CERT_MARKERS[0] not in text or _CERT_MARKERS[1] not in text:
        return None
    if not text.endswith("\n"):
        text += "\n"
    return text


def load_marzban_client_cert() -> Tuple[str, str]:
    """
    Returns:
        (pem, source) — source нужен только для лога, не содержит сам сертификат.
    """
    configured = (getattr(settings, "MARZBAN_NODE_CERT_FILE", None) or "").strip()
    candidates = []
    if configured:
        candidates.append((Path(configured), "MARZBAN_NODE_CERT_FILE"))
    base = getattr(settings, "BASE_DIR", None)
    if base:
        candidates.append(
            (Path(base) / "docs" / "secrets" / "marzban_node_certificate.pem", "docs/secrets"),
        )
    for path, label in candidates:
        if not path.is_file():
            continue
        pem = _valid_cert_pem(path.read_text(encoding="utf-8"))
        if pem:
            return pem, label
    legacy = _valid_cert_pem(_LEGACY_CLIENT_CERT_PEM)
    if not legacy:
        raise ValueError("встроенный client certificate Marzban повреждён")
    return legacy, "legacy"


def build_marzban_node_install_script(cert_pem: str) -> str:
    """
    Bash: docker + compose как у официального установщика, cert с настоящими переносами строк.
    Успех — строка MARZBAN_NODE_UP и exit 0.
    """
    pem = _valid_cert_pem(cert_pem)
    if not pem:
        raise ValueError("client certificate Marzban пустой или без PEM-маркеров")
    if "MARZBAN_CERT_EOF" in pem:
        raise ValueError("сертификат содержит маркер heredoc")
    return f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if ! command -v curl >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y curl ca-certificates
  fi
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if docker compose version >/dev/null 2>&1; then
  compose() {{ docker compose "$@"; }}
elif command -v docker-compose >/dev/null 2>&1; then
  compose() {{ docker-compose "$@"; }}
else
  echo "docker compose не установлен" >&2
  exit 1
fi

mkdir -p /opt/marzban-node /var/lib/marzban-node
cat > /var/lib/marzban-node/cert.pem << 'MARZBAN_CERT_EOF'
{pem.strip()}
MARZBAN_CERT_EOF
chmod 600 /var/lib/marzban-node/cert.pem

if [ -d /root/Marzban-node ]; then
  (cd /root/Marzban-node && compose down) >/dev/null 2>&1 || true
fi
old_ids="$(docker ps -aq --filter ancestor=gozargah/marzban-node:latest || true)"
if [ -n "$old_ids" ]; then
  docker rm -f $old_ids >/dev/null 2>&1 || true
fi
docker rm -f marzban-node >/dev/null 2>&1 || true

cat > /opt/marzban-node/docker-compose.yml << 'MARZBAN_COMPOSE_EOF'
services:
  marzban-node:
    container_name: marzban-node
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host
    environment:
      SSL_CLIENT_CERT_FILE: "/var/lib/marzban-node/cert.pem"
      SERVICE_PORT: "62050"
      XRAY_API_PORT: "62051"
      SERVICE_PROTOCOL: "rest"
    volumes:
      - /var/lib/marzban-node:/var/lib/marzban
      - /var/lib/marzban-node:/var/lib/marzban-node
MARZBAN_COMPOSE_EOF

cd /opt/marzban-node
compose -f docker-compose.yml -p marzban-node up -d --remove-orphans

running="false"
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  running="$(docker inspect -f '{{{{.State.Running}}}}' marzban-node 2>/dev/null || echo false)"
  if [ "$running" = "true" ]; then
    break
  fi
  sleep 5
done
if [ "$running" != "true" ]; then
  echo "MARZBAN_NODE_NOT_RUNNING" >&2
  docker ps -a >&2 || true
  exit 1
fi
echo "MARZBAN_NODE_UP"
"""


def _node_display_name(server: Server) -> str:
    country_label = ""
    if getattr(server, "country_id", None) and getattr(server, "country", None):
        country_label = (server.country.name_for_app or server.country.name or "").strip()
    hosting = (server.hosting or "").strip()
    if country_label and hosting:
        return f"{country_label} {hosting}"
    return hosting or country_label or f"server-{server.pk}"


def _ssh_connect(server: Server, *, attempts: int = 3) -> paramiko.SSHClient:
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("пустой ip_address")
    user = (server.user or "root").strip() or "root"
    password = (server.password or "").strip()
    if password in _SERVER_PASSWORD_PLACEHOLDERS:
        raise ValueError("нужен SSH пароль в Server.password")
    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=ip,
                username=user,
                password=password,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(30)
            return client
        except Exception as exc:
            last_error = exc
            try:
                client.close()
            except Exception:
                pass
            if attempt < attempts:
                time.sleep(10)
    raise RuntimeError(f"SSH не удался за {attempts} попытки: {last_error}")


def _run_remote(client: paramiko.SSHClient, script: str, *, timeout: int = 900) -> Tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(script, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def register_marzban_node(server: Server, *, api: Optional[MarzbanAPI] = None) -> Tuple[bool, str]:
    ip = (server.ip_address or "").strip()
    panel = api or MarzbanAPI()
    ok, existing = panel.find_node_ids_by_ip(ip)
    if ok and existing:
        return True, f"уже в панели id={existing[0]}"
    success, result = panel.add_node(ip=ip, name=_node_display_name(server))
    if success:
        return True, "add_node ok"
    ok_again, existing_again = panel.find_node_ids_by_ip(ip)
    if ok_again and existing_again:
        return True, f"уже в панели id={existing_again[0]}"
    return False, f"add_node: {result!r}"


def bootstrap_marzban_for_server(
    server: Server,
    *,
    api: Optional[MarzbanAPI] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
    cert_pem: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    SSH-установка marzban-node и POST /node.
    При успехе — is_activated_vless=True.
    """
    def _emit(level: str, message: str) -> None:
        if log_fn:
            log_fn(level, message)

    ip = (server.ip_address or "").strip()
    if not ip:
        return False, "пустой ip_address"
    password = (server.password or "").strip()
    if not password or password in _SERVER_PASSWORD_PLACEHOLDERS:
        return False, "нужен SSH пароль в Server.password"

    try:
        if cert_pem:
            pem = _valid_cert_pem(cert_pem)
            source = "argument"
            if not pem:
                return False, "переданный client certificate не PEM"
        else:
            pem, source = load_marzban_client_cert()
        script = build_marzban_node_install_script(pem)
    except Exception as exc:
        return False, str(exc)

    _emit("DEBUG", f"SSH установка marzban-node на {ip} (cert: {source})")
    try:
        client = _ssh_connect(server)
        try:
            code, out, err = _run_remote(client, script)
        finally:
            client.close()
    except Exception as exc:
        return False, f"SSH: {exc}\n{traceback.format_exc()}"

    tail = (err or out or "").strip()[-1500:]
    if code != 0 or "MARZBAN_NODE_UP" not in out:
        return False, f"установка marzban-node exit={code}: {tail}"

    _emit("DEBUG", "контейнер marzban-node запущен, регистрация в панели")
    ok, detail = register_marzban_node(server, api=api)
    if not ok:
        _emit("ERROR", detail)
        return False, detail

    server.is_activated_vless = True
    server.save(update_fields=["is_activated_vless"])
    _emit("INFO", f"готово: {_node_display_name(server)} ({detail})")
    return True, detail
