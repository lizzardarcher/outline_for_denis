"""
TLS-метаданные Hysteria2 с ноды: SNI (CN cert) и pinSHA256 для клиентов без insecure=1.

Pin берётся из /etc/hysteria/cert.pem на сервере (QUIC cert), не с TCP :443 masquerade.
"""
from __future__ import annotations


import re
from typing import Any, Callable, Optional, Tuple

import paramiko
from django.conf import settings
from django.utils import timezone

from bot.models import Server

_DEFAULT_CERT_PATH = "/etc/hysteria/cert.pem"

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))

_FETCH_CMD_TEMPLATE = r"""
set -e
CERT="{cert_path}"
test -f "$CERT"
openssl x509 -in "$CERT" -noout -fingerprint -sha256
openssl x509 -in "$CERT" -noout -subject
"""


def _cert_path() -> str:
    return (getattr(settings, "HYSTERIA_CERT_PATH", None) or _DEFAULT_CERT_PATH).strip()


def parse_pin_sha256_from_fingerprint_line(line: str) -> str:
    """
    sha256 Fingerprint=3E:0C:AA:... → 3E0CAA... (uppercase hex, без двоеточий).
    """
    raw = (line or "").strip()
    if "=" in raw:
        raw = raw.split("=", 1)[1].strip()
    return raw.replace(":", "").upper()


def parse_sni_from_subject_line(line: str) -> str:
    """
    subject=CN = bing.com → bing.com
    subject=C=US, CN=example.com → example.com
    """
    raw = (line or "").strip()
    if raw.lower().startswith("subject="):
        raw = raw.split("=", 1)[1].strip()
    match = re.search(r"(?:^|,\s*)CN\s*=\s*([^,/]+)", raw, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def parse_hysteria_cert_ssh_output(stdout: str) -> Tuple[str, str]:
    """
    Returns (pin_sha256_hex, sni). Raises ValueError on invalid output.
    """
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    fp_line = next((ln for ln in lines if "fingerprint" in ln.lower()), "")
    subj_line = next((ln for ln in lines if ln.lower().startswith("subject=")), "")
    pin = parse_pin_sha256_from_fingerprint_line(fp_line)
    sni = parse_sni_from_subject_line(subj_line)
    if len(pin) != 64 or not all(c in "0123456789ABCDEF" for c in pin):
        raise ValueError(f"некорректный pin SHA-256: {fp_line!r}")
    if not sni:
        raise ValueError(f"не удалось извлечь CN из subject: {subj_line!r}")
    return pin, sni


def _ssh_connect(server: Server) -> paramiko.SSHClient:
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("пустой ip_address")
    user = (server.user or "root").strip() or "root"
    password = (server.password or "").strip()
    key_pem = (getattr(settings, "CELERITY_SSH_PRIVATE_KEY", None) or "").strip()
    if password in _SERVER_PASSWORD_PLACEHOLDERS:
        password = ""
    if not password and not key_pem:
        raise ValueError("нужен SSH password или CELERITY_SSH_PRIVATE_KEY")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kw = {
        "hostname": ip,
        "username": user,
        "timeout": 20,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key_pem:
        import io

        pkey = None
        for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                pkey = key_cls.from_private_key(io.StringIO(key_pem))
                break
            except paramiko.SSHException:
                continue
        if pkey is None:
            raise ValueError("не удалось прочитать CELERITY_SSH_PRIVATE_KEY")
        connect_kw["pkey"] = pkey
    else:
        connect_kw["password"] = password
    client.connect(**connect_kw)
    return client


def fetch_hysteria_tls_meta_via_ssh(server: Server) -> Tuple[str, str]:
    """
    SSH на ноду, читает /etc/hysteria/cert.pem.

    Returns:
        (pin_sha256_hex_upper, sni)
    """
    cert_path = _cert_path()
    cmd = _FETCH_CMD_TEMPLATE.format(cert_path=cert_path)
    client = _ssh_connect(server)
    try:
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            raise RuntimeError(err.strip() or out.strip() or f"exit {exit_code}")
        return parse_hysteria_cert_ssh_output(out)
    finally:
        client.close()


def save_hysteria_tls_meta_to_server(server: Server, *, pin: str, sni: str) -> None:
    server.hysteria_pin_sha256 = pin
    server.hysteria_tls_sni = sni
    server.hysteria_cert_synced_at = timezone.now()
    server.save(
        update_fields=[
            "hysteria_pin_sha256",
            "hysteria_tls_sni",
            "hysteria_cert_synced_at",
        ]
    )


def sync_hysteria_tls_meta_for_server(server: Server) -> Tuple[bool, str]:
    """
    Снимает pin/SNI по SSH и сохраняет в Server.

    Returns:
        (True, "OK") или (False, сообщение об ошибке)
    """
    try:
        pin, sni = fetch_hysteria_tls_meta_via_ssh(server)
        save_hysteria_tls_meta_to_server(server, pin=pin, sni=sni)
        return True, f"pin={pin[:8]}… sni={sni}"
    except Exception as e:
        return False, str(e)


def try_sync_hysteria_tls_meta_after_setup(
    server: Server,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> None:
    """После Celerity setup: best-effort sync pin/SNI (не блокирует активацию ноды)."""
    ok, detail = sync_hysteria_tls_meta_for_server(server)
    if log_fn:
        level = "INFO" if ok else "WARNING"
        log_fn(level, f"hysteria TLS meta: {detail}")
