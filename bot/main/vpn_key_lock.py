from django.core.cache import cache

VPN_KEY_CREATE_LOCK_PREFIX = "vpn_key_create:"
VPN_KEY_CREATE_LOCK_TTL = 120


def vpn_key_create_lock_key(user_id) -> str:
    return f"{VPN_KEY_CREATE_LOCK_PREFIX}{user_id}"



def acquire_vpn_key_create_lock(user_id) -> bool:
    """Return True if lock acquired (caller may proceed with key creation)."""
    return cache.add(vpn_key_create_lock_key(user_id), "1", timeout=VPN_KEY_CREATE_LOCK_TTL)


def release_vpn_key_create_lock(user_id) -> None:
    cache.delete(vpn_key_create_lock_key(user_id))
