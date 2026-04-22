from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProxyNode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, verbose_name="Название ноды")),
                ("host", models.CharField(max_length=255, unique=True, verbose_name="IP/Host")),
                ("proxy_port", models.PositiveIntegerField(default=443, verbose_name="Порт proxy")),
                ("ssh_port", models.PositiveIntegerField(default=22, verbose_name="SSH порт")),
                ("ssh_username", models.CharField(default="root", max_length=255, verbose_name="SSH user")),
                ("ssh_password", models.CharField(blank=True, default="", max_length=1000, verbose_name="SSH пароль")),
                (
                    "install_script",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Кастомный bash-скрипт установки. Если пусто — используется стандартный.",
                        verbose_name="Install script",
                    ),
                ),
                ("capacity", models.PositiveIntegerField(default=10000, verbose_name="Лимит ключей")),
                ("is_active", models.BooleanField(default=True, verbose_name="Нода активна")),
                ("auto_install_on_create", models.BooleanField(default=True, verbose_name="Автоустановка при создании")),
                ("is_software_installed", models.BooleanField(default=False, verbose_name="ПО установлено")),
                (
                    "install_state",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидает установки"),
                            ("installing", "Установка"),
                            ("installed", "Установлено"),
                            ("failed", "Ошибка установки"),
                        ],
                        default="pending",
                        max_length=24,
                        verbose_name="Статус установки",
                    ),
                ),
                ("installed_at", models.DateTimeField(blank=True, null=True, verbose_name="Установлено в")),
                ("last_install_error", models.TextField(blank=True, default="", verbose_name="Последняя ошибка установки")),
                (
                    "health_state",
                    models.CharField(
                        choices=[("unknown", "Не проверено"), ("up", "UP"), ("down", "DOWN")],
                        default="unknown",
                        max_length=24,
                        verbose_name="Health",
                    ),
                ),
                ("last_healthcheck_at", models.DateTimeField(blank=True, null=True, verbose_name="Последний health-check")),
                ("last_health_error", models.TextField(blank=True, default="", verbose_name="Последняя ошибка health-check")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                (
                    "country",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="bot.country",
                        verbose_name="Страна",
                    ),
                ),
            ],
            options={
                "verbose_name": "MTProto нода",
                "verbose_name_plural": "MTProto ноды",
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="ProxyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("install_started", "Install started"),
                            ("install_success", "Install success"),
                            ("install_failed", "Install failed"),
                            ("health_down", "Health down"),
                            ("health_up", "Health up"),
                            ("key_issued", "Key issued"),
                            ("key_reissued", "Key reissued"),
                            ("key_revoked", "Key revoked"),
                        ],
                        max_length=64,
                        verbose_name="Тип события",
                    ),
                ),
                ("message", models.TextField(blank=True, default="", verbose_name="Сообщение")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                (
                    "node",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="mtproxy.proxynode",
                        verbose_name="Нода",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="bot.telegramuser",
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "MTProto событие",
                "verbose_name_plural": "MTProto события",
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="ProxyAccessKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("secret", models.CharField(max_length=128, unique=True, verbose_name="MTProto secret")),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Активен"), ("revoked", "Отозван")],
                        default="active",
                        max_length=24,
                        verbose_name="Статус",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="Отозван")),
                ("revoke_reason", models.CharField(blank=True, default="", max_length=255, verbose_name="Причина отзыва")),
                ("node", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="mtproxy.proxynode", verbose_name="Нода")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proxy_keys",
                        to="bot.telegramuser",
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "MTProto ключ",
                "verbose_name_plural": "MTProto ключи",
                "ordering": ["-id"],
                "indexes": [models.Index(fields=["user", "status"], name="mtproxy_prox_user_id_2bd4ca_idx"), models.Index(fields=["node", "status"], name="mtproxy_prox_node_id_c32b9a_idx")],
            },
        ),
    ]
