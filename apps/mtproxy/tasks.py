import socket
import shlex
import traceback

import paramiko
import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.mtproxy.models import ProxyAccessKey, ProxyEvent, ProxyNode, ProxyUsageSnapshot
from bot.models import Logging
from bot.models import TelegramUser


DEFAULT_INSTALL_SCRIPT = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl ca-certificates
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
curl -fsSL https://raw.githubusercontent.com/SamNet-dev/MTProxyMax/main/mtproxymax.sh -o /root/mtproxymax.sh
chmod +x /root/mtproxymax.sh
touch /root/.mtproxymax_installed
"""


def _create_log(message, level="INFO"):
    try:
        Logging.objects.create(log_level=level, message=message, datetime=timezone.now(), user=None)
    except Exception:
        pass


def _ssh_exec(node: ProxyNode, command: str):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=node.host,
        port=node.ssh_port,
        username=node.ssh_username,
        password=node.ssh_password,
        timeout=20,
    )
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    code = stdout.channel.recv_exit_status()
    client.close()
    return code, out, err


def _ssh_exec_bash(node: ProxyNode, command: str):
    # Выполняем через login-shell, чтобы mtproxymax из PATH корректно находился.
    wrapped = f"bash -lc {shlex.quote(command)}"
    return _ssh_exec(node, wrapped)


def _to_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _extract_metrics_map(body):
    """
    Поддерживаем несколько JSON форматов:
    1) {"secrets": {"<secret>": {...}}}
    2) {"<secret>": {...}}
    3) [{"secret": "...", "concurrent_connections": ...}, ...]
    """
    if isinstance(body, dict):
        if isinstance(body.get("secrets"), dict):
            return body["secrets"]
        # Если dict верхнего уровня уже похож на map secret->metrics
        if body and all(isinstance(v, dict) for v in body.values()):
            return body
    elif isinstance(body, list):
        result = {}
        for row in body:
            if isinstance(row, dict) and row.get("secret"):
                result[str(row["secret"])] = row
        return result
    return {}


def _fetch_node_metrics(node: ProxyNode):
    url = (node.metrics_url or "").strip()
    if not url:
        return {}
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        body = resp.json()
        return _extract_metrics_map(body)
    except Exception as exc:
        _create_log(f"[MTPROXY] [METRICS] fetch failed node={node.host} err={exc}", level="WARNING")
        return {}


def _create_usage_snapshots_for_node(node: ProxyNode, source_prefix="healthcheck"):
    now = timezone.now()
    active_keys = ProxyAccessKey.objects.filter(node=node, status=ProxyAccessKey.STATUS_ACTIVE).order_by("id")
    if not active_keys.exists():
        return 0

    metrics_map = _fetch_node_metrics(node)
    created = 0
    for key in active_keys:
        latest = key.usage_snapshots.order_by("-captured_at").first()
        if latest and (now - latest.captured_at).total_seconds() < 50:
            continue

        row = metrics_map.get(key.secret) or {}
        has_external = bool(row)
        ProxyUsageSnapshot.objects.create(
            key=key,
            concurrent_connections=_to_int(row.get("concurrent_connections")),
            new_sessions_5m=_to_int(row.get("new_sessions_5m")),
            unique_ip_24h=_to_int(row.get("unique_ip_24h")),
            bytes_in=_to_int(row.get("bytes_in")),
            bytes_out=_to_int(row.get("bytes_out")),
            source=f"{source_prefix}_metrics" if has_external else f"{source_prefix}_fallback",
            captured_at=now,
        )
        created += 1
    return created


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def install_mtproxy_node_task(self, node_id: int, force: bool = False):
    node = ProxyNode.objects.filter(id=node_id).first()
    if not node:
        return "node_not_found"

    if node.is_software_installed and not force:
        return "already_installed"

    with transaction.atomic():
        node = ProxyNode.objects.select_for_update().get(id=node_id)
        if node.is_software_installed and not force:
            return "already_installed"
        node.install_state = ProxyNode.INSTALL_STATE_INSTALLING
        node.last_install_error = ""
        node.save(update_fields=["install_state", "last_install_error", "updated_at"])

    ProxyEvent.objects.create(
        event_type=ProxyEvent.EVENT_INSTALL_STARTED,
        node=node,
        message="Запущена установка MTProxy ПО",
    )
    _create_log(f"[MTPROXY] [INSTALL] start node={node.host}")

    script = (node.install_script or "").strip() or DEFAULT_INSTALL_SCRIPT
    try:
        code, out, err = _ssh_exec(node, script)
        if code != 0:
            raise RuntimeError(f"install_exit_code={code}; stderr={err[:2000]}")

        node.install_state = ProxyNode.INSTALL_STATE_INSTALLED
        node.is_software_installed = True
        node.installed_at = timezone.now()
        node.last_install_error = ""
        node.save(
            update_fields=[
                "install_state",
                "is_software_installed",
                "installed_at",
                "last_install_error",
                "updated_at",
            ]
        )
        ProxyEvent.objects.create(
            event_type=ProxyEvent.EVENT_INSTALL_SUCCESS,
            node=node,
            message="Установка завершена успешно",
        )
        _create_log(f"[MTPROXY] [INSTALL] success node={node.host}")
        return "ok"
    except Exception as exc:
        err_text = f"{exc}\n{traceback.format_exc()}"[:4000]
        node.install_state = ProxyNode.INSTALL_STATE_FAILED
        node.is_software_installed = False
        node.last_install_error = err_text
        node.save(update_fields=["install_state", "is_software_installed", "last_install_error", "updated_at"])
        ProxyEvent.objects.create(
            event_type=ProxyEvent.EVENT_INSTALL_FAILED,
            node=node,
            message=err_text[:1000],
        )
        _create_log(f"[MTPROXY] [INSTALL] failed node={node.host}; {exc}", level="FATAL")
        raise self.retry(exc=exc)


@shared_task
def healthcheck_mtproxy_nodes_task():
    nodes = ProxyNode.objects.filter(is_active=True, is_software_installed=True)
    for node in nodes:
        prev = node.health_state
        try:
            with socket.create_connection((node.host, int(node.proxy_port)), timeout=5):
                pass
            node.health_state = ProxyNode.HEALTH_UP
            node.last_health_error = ""
        except Exception as exc:
            node.health_state = ProxyNode.HEALTH_DOWN
            node.last_health_error = str(exc)[:500]

        node.last_healthcheck_at = timezone.now()
        node.save(update_fields=["health_state", "last_health_error", "last_healthcheck_at", "updated_at"])

        # Автосоздание usage snapshots при каждом health-check цикле.
        _create_usage_snapshots_for_node(node, source_prefix="healthcheck")

        if prev != node.health_state:
            event_type = ProxyEvent.EVENT_HEALTH_UP if node.health_state == ProxyNode.HEALTH_UP else ProxyEvent.EVENT_HEALTH_DOWN
            ProxyEvent.objects.create(
                event_type=event_type,
                node=node,
                message=f"health: {prev} -> {node.health_state}",
            )
            _create_log(f"[MTPROXY] [HEALTH] {node.host} {prev}->{node.health_state}", level="WARNING")


@shared_task
def collect_mtproxy_usage_snapshots_task(node_id=None):
    """
    Явный запуск сбора usage snapshots.
    Если node_id не передан — собираем по всем активным установленным нодам.
    """
    qs = ProxyNode.objects.filter(is_active=True, is_software_installed=True)
    if node_id is not None:
        qs = qs.filter(id=node_id)
    total = 0
    for node in qs:
        total += _create_usage_snapshots_for_node(node, source_prefix="manual")
    return total


@shared_task
def sync_mtproxy_key_with_node_task(key_id: int, action: str):
    """
    Best-effort синхронизация ключа с нодой через SSH + mtproxymax CLI:
    action: issue | revoke
    """
    key = ProxyAccessKey.objects.select_related("node", "user").filter(id=key_id).first()
    if not key:
        return "key_not_found"
    node = key.node
    secret = key.secret
    mtproxy_id = f"user_{key.user.user_id}_{key.id}"

    if action == "issue":
        command_candidates = [
            # Варианты на случай отличий CLI версии MTProxyMax.
            f"mtproxymax secret add {shlex.quote(secret)} --no-restart",
            f"mtproxymax secret add --secret {shlex.quote(secret)} --no-restart",
            f"mtproxymax secret add {shlex.quote(mtproxy_id)} {shlex.quote(secret)} --no-restart",
        ]
    elif action == "revoke":
        command_candidates = [
            f"mtproxymax secret remove {shlex.quote(secret)} --no-restart",
            f"mtproxymax secret disable {shlex.quote(secret)} --no-restart",
            f"mtproxymax secret remove {shlex.quote(mtproxy_id)} --no-restart",
        ]
    else:
        return "bad_action"

    last_error = ""
    for command in command_candidates:
        try:
            code, out, err = _ssh_exec_bash(node, command)
            if code == 0:
                ProxyEvent.objects.create(
                    event_type=ProxyEvent.EVENT_KEY_ISSUED if action == "issue" else ProxyEvent.EVENT_KEY_REVOKED,
                    node=node,
                    user=key.user,
                    message=f"[SYNC/SSH] action={action} key={key.id} cmd={command}",
                )
                return "ok"
            last_error = f"code={code}; stderr={err[:300]}"
        except Exception as exc:
            last_error = str(exc)

    msg = f"[SYNC/SSH] failed action={action} key={key.id} err={last_error}"
    _create_log(f"[MTPROXY] {msg}", level="WARNING")
    ProxyEvent.objects.create(
        event_type=ProxyEvent.EVENT_INSTALL_FAILED,
        node=node,
        user=key.user,
        message=msg[:1000],
    )
    return "failed"


@shared_task
def calculate_mtproxy_abuse_score_task():
    """
    Рассчитывает anti-abuse score по последнему usage snapshot:
    - unique_ip_24h > 5   => +2
    - new_sessions_5m >30 => +3
    - concurrent_conn >10 => +3
    При отсутствии нарушений score плавно снижается.
    Критика: score >= 12 => автоматический revoke ключа.
    """
    now = timezone.now()
    active_keys = (
        ProxyAccessKey.objects.filter(status=ProxyAccessKey.STATUS_ACTIVE)
        .select_related("node", "user")
        .order_by("id")
    )
    for key in active_keys:
        snapshot = key.usage_snapshots.order_by("-captured_at", "-id").first()
        prev_score = int(key.abuse_score or 0)
        delta = 0
        reasons = []

        if snapshot:
            if snapshot.unique_ip_24h > 5:
                delta += 2
                reasons.append(f"unique_ip_24h={snapshot.unique_ip_24h}>5")
            if snapshot.new_sessions_5m > 30:
                delta += 3
                reasons.append(f"new_sessions_5m={snapshot.new_sessions_5m}>30")
            if snapshot.concurrent_connections > 10:
                delta += 3
                reasons.append(f"concurrent_connections={snapshot.concurrent_connections}>10")

        if delta > 0:
            new_score = prev_score + delta
        else:
            # Медленный decay, чтобы нормальный пользователь "восстанавливался"
            if prev_score > 0 and (
                key.last_abuse_check_at is None or (now - key.last_abuse_check_at).total_seconds() >= 3600
            ):
                new_score = max(0, prev_score - 1)
            else:
                new_score = prev_score

        key.abuse_score = new_score
        key.last_abuse_check_at = now
        key.save(update_fields=["abuse_score", "last_abuse_check_at"])

        if delta > 0 and prev_score < 5 <= new_score:
            ProxyEvent.objects.create(
                event_type=ProxyEvent.EVENT_ABUSE_FLAG,
                node=key.node,
                user=key.user,
                message=f"[ABUSE] medium threshold reached; score={new_score}; reasons={'; '.join(reasons)}",
            )

        if delta > 0 and prev_score < 8 <= new_score:
            ProxyEvent.objects.create(
                event_type=ProxyEvent.EVENT_ABUSE_FLAG,
                node=key.node,
                user=key.user,
                message=f"[ABUSE] high threshold reached; score={new_score}; reasons={'; '.join(reasons)}",
            )

        if prev_score < 12 <= new_score:
            key.revoke(reason="anti_abuse_auto")
            sync_mtproxy_key_with_node_task.delay(key.id, "revoke")
            ProxyEvent.objects.create(
                event_type=ProxyEvent.EVENT_KEY_REVOKED,
                node=key.node,
                user=key.user,
                message=f"[ABUSE] auto revoke; score={new_score}",
            )
            _create_log(
                f"[MTPROXY] [ABUSE] key={key.id} user={key.user.user_id} auto-revoked score={new_score}",
                level="WARNING",
            )


@shared_task
def revoke_mtproxy_keys_for_user_task(telegram_user_id: int, reason: str = "subscription_inactive"):
    user = TelegramUser.objects.filter(user_id=telegram_user_id).first()
    if not user:
        return 0
    active_keys = ProxyAccessKey.objects.filter(user=user, status=ProxyAccessKey.STATUS_ACTIVE).select_related("node")
    count = 0
    for key in active_keys:
        key.revoke(reason=reason)
        sync_mtproxy_key_with_node_task.delay(key.id, "revoke")
        ProxyEvent.objects.create(
            event_type=ProxyEvent.EVENT_KEY_REVOKED,
            node=key.node,
            user=user,
            message=f"[AUTO] revoke by rule reason={reason} key={key.id}",
        )
        count += 1
    return count


@shared_task
def revoke_mtproxy_keys_for_inactive_subscriptions_task():
    users = TelegramUser.objects.filter(subscription_status=False).only("id", "user_id")
    total = 0
    for user in users:
        total += revoke_mtproxy_keys_for_user_task.run(user.user_id, reason="subscription_inactive")
    return total
