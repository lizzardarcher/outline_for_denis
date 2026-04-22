import secrets

from django.db import transaction

from apps.mtproxy.models import ProxyAccessKey, ProxyEvent, ProxyNode
from apps.mtproxy.tasks import sync_mtproxy_key_with_node_task
from bot.models import TelegramUser


def can_use_mtproxy(user: TelegramUser) -> bool:
    return bool(user and (user.username or "").strip().lower() == "megafoll")


def get_active_key(user: TelegramUser):
    return ProxyAccessKey.objects.filter(user=user, status=ProxyAccessKey.STATUS_ACTIVE).select_related("node").first()


def choose_available_node():
    nodes = (
        ProxyNode.objects.filter(
            is_active=True,
            is_software_installed=True,
            install_state=ProxyNode.INSTALL_STATE_INSTALLED,
            health_state=ProxyNode.HEALTH_UP,
        )
        .order_by("id")
    )
    for node in nodes:
        if not node.is_overloaded:
            return node
    return None


@transaction.atomic
def issue_or_get_key(user: TelegramUser):
    existing = get_active_key(user)
    if existing:
        return existing, False

    node = choose_available_node()
    if not node:
        return None, False

    secret = secrets.token_hex(16)
    key = ProxyAccessKey.objects.create(
        user=user,
        node=node,
        secret=secret,
        status=ProxyAccessKey.STATUS_ACTIVE,
    )
    ProxyEvent.objects.create(
        event_type=ProxyEvent.EVENT_KEY_ISSUED,
        node=node,
        user=user,
        message=f"Выдан новый ключ {key.id}",
    )
    sync_mtproxy_key_with_node_task.delay(key.id, "issue")
    return key, True


def revoke_all_user_keys(user: TelegramUser, reason="manual_revoke"):
    active_keys = ProxyAccessKey.objects.filter(user=user, status=ProxyAccessKey.STATUS_ACTIVE).select_related("node")
    revoked = 0
    for key in active_keys:
        key.revoke(reason=reason)
        sync_mtproxy_key_with_node_task.delay(key.id, "revoke")
        ProxyEvent.objects.create(
            event_type=ProxyEvent.EVENT_KEY_REVOKED,
            node=key.node,
            user=user,
            message=f"Ключ {key.id} отозван. reason={reason}",
        )
        revoked += 1
    return revoked


@transaction.atomic
def reissue_key(user: TelegramUser):
    existing = get_active_key(user)
    if existing:
        revoke_all_user_keys(user, reason="manual_reissue")

    key, _ = issue_or_get_key(user)
    if key:
        ProxyEvent.objects.create(
            event_type=ProxyEvent.EVENT_KEY_REISSUED,
            node=key.node,
            user=user,
            message=f"Перевыдан ключ {key.id}",
        )
    return key
