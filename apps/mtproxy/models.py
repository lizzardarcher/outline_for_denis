from django.db import models
from django.utils import timezone

from bot.models import Country, TelegramUser


class ProxyNode(models.Model):
    INSTALL_STATE_PENDING = "pending"
    INSTALL_STATE_INSTALLING = "installing"
    INSTALL_STATE_INSTALLED = "installed"
    INSTALL_STATE_FAILED = "failed"
    INSTALL_STATES = (
        (INSTALL_STATE_PENDING, "Ожидает установки"),
        (INSTALL_STATE_INSTALLING, "Установка"),
        (INSTALL_STATE_INSTALLED, "Установлено"),
        (INSTALL_STATE_FAILED, "Ошибка установки"),
    )

    HEALTH_UNKNOWN = "unknown"
    HEALTH_UP = "up"
    HEALTH_DOWN = "down"
    HEALTH_STATES = (
        (HEALTH_UNKNOWN, "Не проверено"),
        (HEALTH_UP, "UP"),
        (HEALTH_DOWN, "DOWN"),
    )

    name = models.CharField(max_length=255, verbose_name="Название ноды")
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Страна")
    host = models.CharField(max_length=255, unique=True, verbose_name="IP/Host")
    proxy_port = models.PositiveIntegerField(default=443, verbose_name="Порт proxy")
    ssh_port = models.PositiveIntegerField(default=22, verbose_name="SSH порт")
    ssh_username = models.CharField(max_length=255, default="root", verbose_name="SSH user")
    ssh_password = models.CharField(max_length=1000, blank=True, default="", verbose_name="SSH пароль")
    install_script = models.TextField(
        blank=True,
        default="",
        verbose_name="Install script",
        help_text="Кастомный bash-скрипт установки. Если пусто — используется стандартный.",
    )
    manage_api_url = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="Manage API URL",
        help_text="Endpoint управления секретами ноды (опционально). Пример: http://IP:9090/manage",
    )
    manage_api_token = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="Manage API token",
        help_text="Bearer token для manage API (опционально).",
    )
    metrics_url = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="Metrics URL",
        help_text="JSON endpoint метрик ноды (опционально). Пример: http://IP:9090/stats",
    )
    capacity = models.PositiveIntegerField(default=10000, verbose_name="Лимит ключей")
    is_active = models.BooleanField(default=True, verbose_name="Нода активна")
    auto_install_on_create = models.BooleanField(default=True, verbose_name="Автоустановка при создании")

    is_software_installed = models.BooleanField(default=False, verbose_name="ПО установлено")
    install_state = models.CharField(
        max_length=24,
        choices=INSTALL_STATES,
        default=INSTALL_STATE_PENDING,
        verbose_name="Статус установки",
    )
    installed_at = models.DateTimeField(null=True, blank=True, verbose_name="Установлено в")
    last_install_error = models.TextField(blank=True, default="", verbose_name="Последняя ошибка установки")

    health_state = models.CharField(
        max_length=24,
        choices=HEALTH_STATES,
        default=HEALTH_UNKNOWN,
        verbose_name="Health",
    )
    last_healthcheck_at = models.DateTimeField(null=True, blank=True, verbose_name="Последний health-check")
    last_health_error = models.TextField(blank=True, default="", verbose_name="Последняя ошибка health-check")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "MTProto нода"
        verbose_name_plural = "MTProto ноды"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name} ({self.host}:{self.proxy_port})"

    @property
    def issued_keys_count(self):
        return self.proxyaccesskey_set.filter(status=ProxyAccessKey.STATUS_ACTIVE).count()

    @property
    def is_overloaded(self):
        return self.issued_keys_count >= self.capacity


class ProxyAccessKey(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Активен"),
        (STATUS_REVOKED, "Отозван"),
    )

    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name="proxy_keys", verbose_name="Пользователь")
    node = models.ForeignKey(ProxyNode, on_delete=models.PROTECT, verbose_name="Нода")
    secret = models.CharField(max_length=128, unique=True, verbose_name="MTProto secret")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_ACTIVE, verbose_name="Статус")
    abuse_score = models.PositiveIntegerField(default=0, verbose_name="Anti-abuse score")
    last_abuse_check_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя проверка anti-abuse")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="Отозван")
    revoke_reason = models.CharField(max_length=255, blank=True, default="", verbose_name="Причина отзыва")

    class Meta:
        verbose_name = "MTProto ключ"
        verbose_name_plural = "MTProto ключи"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["node", "status"]),
        ]

    def __str__(self):
        return f"{self.user.user_id} -> {self.node.host}:{self.node.proxy_port} [{self.status}]"

    @property
    def tg_proxy_link(self):
        return f"tg://proxy?server={self.node.host}&port={self.node.proxy_port}&secret={self.secret}"

    @property
    def web_proxy_link(self):
        return f"https://t.me/proxy?server={self.node.host}&port={self.node.proxy_port}&secret={self.secret}"

    def revoke(self, reason=""):
        self.status = self.STATUS_REVOKED
        self.revoked_at = timezone.now()
        self.revoke_reason = reason or ""
        self.save(update_fields=["status", "revoked_at", "revoke_reason"])


class ProxyUsageSnapshot(models.Model):
    key = models.ForeignKey(ProxyAccessKey, on_delete=models.CASCADE, related_name="usage_snapshots", verbose_name="Ключ")
    concurrent_connections = models.PositiveIntegerField(default=0, verbose_name="Одновременных соединений")
    new_sessions_5m = models.PositiveIntegerField(default=0, verbose_name="Новых сессий за 5 мин")
    unique_ip_24h = models.PositiveIntegerField(default=0, verbose_name="Уникальных IP за 24ч")
    bytes_in = models.BigIntegerField(default=0, verbose_name="Входящий трафик, байт")
    bytes_out = models.BigIntegerField(default=0, verbose_name="Исходящий трафик, байт")
    source = models.CharField(max_length=64, blank=True, default="manual", verbose_name="Источник метрик")
    captured_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Время среза")

    class Meta:
        verbose_name = "MTProto срез метрик"
        verbose_name_plural = "MTProto срезы метрик"
        ordering = ["-captured_at", "-id"]
        indexes = [
            models.Index(fields=["key", "captured_at"]),
        ]

    def __str__(self):
        return (
            f"key={self.key_id} cc={self.concurrent_connections} "
            f"s5m={self.new_sessions_5m} ip24={self.unique_ip_24h}"
        )


class ProxyEvent(models.Model):
    EVENT_INSTALL_STARTED = "install_started"
    EVENT_INSTALL_SUCCESS = "install_success"
    EVENT_INSTALL_FAILED = "install_failed"
    EVENT_HEALTH_DOWN = "health_down"
    EVENT_HEALTH_UP = "health_up"
    EVENT_KEY_ISSUED = "key_issued"
    EVENT_KEY_REISSUED = "key_reissued"
    EVENT_KEY_REVOKED = "key_revoked"
    EVENT_ABUSE_FLAG = "abuse_flag"
    EVENT_TYPES = (
        (EVENT_INSTALL_STARTED, "Install started"),
        (EVENT_INSTALL_SUCCESS, "Install success"),
        (EVENT_INSTALL_FAILED, "Install failed"),
        (EVENT_HEALTH_DOWN, "Health down"),
        (EVENT_HEALTH_UP, "Health up"),
        (EVENT_KEY_ISSUED, "Key issued"),
        (EVENT_KEY_REISSUED, "Key reissued"),
        (EVENT_KEY_REVOKED, "Key revoked"),
        (EVENT_ABUSE_FLAG, "Abuse flag"),
    )

    event_type = models.CharField(max_length=64, choices=EVENT_TYPES, verbose_name="Тип события")
    node = models.ForeignKey(ProxyNode, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Нода")
    user = models.ForeignKey(TelegramUser, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Пользователь")
    message = models.TextField(blank=True, default="", verbose_name="Сообщение")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "MTProto событие"
        verbose_name_plural = "MTProto события"
        ordering = ["-id"]

    def __str__(self):
        return f"[{self.event_type}] {self.created_at:%Y-%m-%d %H:%M:%S}"
