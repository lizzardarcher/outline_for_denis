
"""Сброс кэша AdminDashboardX (JSON-агрегаты) после изменений данных."""

from django.core.cache import cache


def bust_admx_dashboard_caches():
    """
    Удаляет ключи аналитики доходов и главной.
    Рассчитано на django-redis (delete_pattern); при другом backend — no-op по паттерну.
    """
    try:
        cache.delete("admx:index:data:v1")
    except Exception:
        pass
    try:
        if hasattr(cache, "delete_pattern"):
            cache.delete_pattern("admx:revenue:data:v3:*")
    except Exception:
        pass
