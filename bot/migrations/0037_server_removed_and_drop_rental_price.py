
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot", "0036_server_ip_address_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServerRemoved",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_id", models.IntegerField(verbose_name="ID сервера")),
                ("hosting", models.CharField(blank=True, max_length=1000, null=True, verbose_name="Хостинг")),
                ("ip_address", models.CharField(blank=True, max_length=1000, null=True, verbose_name="IP Address")),
                ("user", models.CharField(blank=True, max_length=1000, null=True, verbose_name="Пользователь")),
                ("password", models.CharField(blank=True, max_length=1000, null=True, verbose_name="Пароль")),
                ("max_keys", models.IntegerField(blank=True, null=True, verbose_name="Лимит ключей")),
                ("keys_generated", models.IntegerField(blank=True, null=True, verbose_name="Ключей сгенерировано")),
                ("is_active", models.BooleanField(default=False, verbose_name="Сервер Активен")),
                ("created_at", models.DateField(blank=True, null=True, verbose_name="Дата создания")),
                ("country_name", models.CharField(blank=True, default="", max_length=100, verbose_name="Страна")),
                ("country_name_for_app", models.CharField(blank=True, default="", max_length=100, verbose_name="Страна в приложении")),
                ("node_role", models.CharField(blank=True, default="", max_length=16, verbose_name="Протокол сервера")),
                ("is_activated_vless", models.BooleanField(default=False, verbose_name="Панель Vless/SS")),
                ("is_pasarguard_activated", models.BooleanField(default=False, verbose_name="PasarGuard")),
                ("is_c3celeryty_activated", models.BooleanField(default=False, verbose_name="Панель C3 Celeryty")),
                ("hysteria_tls_sni", models.CharField(blank=True, default="", max_length=255, verbose_name="Hysteria TLS SNI")),
                ("hysteria_pin_sha256", models.CharField(blank=True, default="", max_length=64, verbose_name="Hysteria pinSHA256")),
                ("hysteria_cert_synced_at", models.DateTimeField(blank=True, null=True, verbose_name="Hysteria cert sync")),
                ("removed_at", models.DateTimeField(auto_now_add=True, verbose_name="Удалён")),
            ],
            options={
                "verbose_name": "Удалённый VPN сервер",
                "verbose_name_plural": "Удалённые VPN сервера",
                "ordering": ("-removed_at", "-id"),
            },
        ),
        migrations.RemoveField(
            model_name="server",
            name="rental_price",
        ),
    ]
