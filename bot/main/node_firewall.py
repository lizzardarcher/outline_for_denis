"""Правила ufw для сервера с одним протоколом."""
from __future__ import annotations

from bot.models import Server



_RULES = {
    Server.NODE_ROLE_OUTLINE: ("22/tcp", "1080/tcp", "62050/tcp", "62051/tcp"),
    Server.NODE_ROLE_VLESS: ("22/tcp", "443/tcp", "62050/tcp", "62051/tcp"),
    Server.NODE_ROLE_HYSTERIA2: ("22/tcp", "443/tcp", "443/udp"),
}


def ufw_rules_for_role(role: str) -> tuple:
    rules = _RULES.get((role or "").strip())
    if not rules:
        raise ValueError(f"нет правил ufw для роли {role!r}")
    return rules


def build_ufw_commands(role: str) -> str:
    lines = [
        "if ! command -v ufw >/dev/null 2>&1; then",
        "  apt-get update -y",
        "  apt-get install -y ufw",
        "fi",
    ]
    for rule in ufw_rules_for_role(role):
        lines.append(f"ufw allow {rule}")
    lines.extend(
        [
            "ufw default deny incoming",
            "ufw default allow outgoing",
            "ufw --force enable",
            'echo "UFW_ROLE_APPLIED"',
        ]
    )
    return "\n".join(lines)


def build_role_init_script(role: str, marzban_script: str = "") -> str:
    parts = [
        "#!/bin/bash",
        "set -euo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
        build_ufw_commands(role),
    ]
    extra = (marzban_script or "").strip()
    if extra.startswith("#!"):
        extra = extra.split("\n", 1)[1].lstrip("\n")
    if extra:
        parts.append(extra)
    return "\n".join(parts) + "\n"
