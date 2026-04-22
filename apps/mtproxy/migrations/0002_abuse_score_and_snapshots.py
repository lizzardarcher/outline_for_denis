from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("mtproxy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="proxyaccesskey",
            name="abuse_score",
            field=models.PositiveIntegerField(default=0, verbose_name="Anti-abuse score"),
        ),
        migrations.AddField(
            model_name="proxyaccesskey",
            name="last_abuse_check_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Последняя проверка anti-abuse"),
        ),
        migrations.CreateModel(
            name="ProxyUsageSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("concurrent_connections", models.PositiveIntegerField(default=0, verbose_name="Одновременных соединений")),
                ("new_sessions_5m", models.PositiveIntegerField(default=0, verbose_name="Новых сессий за 5 мин")),
                ("unique_ip_24h", models.PositiveIntegerField(default=0, verbose_name="Уникальных IP за 24ч")),
                ("bytes_in", models.BigIntegerField(default=0, verbose_name="Входящий трафик, байт")),
                ("bytes_out", models.BigIntegerField(default=0, verbose_name="Исходящий трафик, байт")),
                ("source", models.CharField(blank=True, default="manual", max_length=64, verbose_name="Источник метрик")),
                ("captured_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="Время среза")),
                (
                    "key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_snapshots",
                        to="mtproxy.proxyaccesskey",
                        verbose_name="Ключ",
                    ),
                ),
            ],
            options={
                "verbose_name": "MTProto срез метрик",
                "verbose_name_plural": "MTProto срезы метрик",
                "ordering": ["-captured_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="proxyusagesnapshot",
            index=models.Index(fields=["key", "captured_at"], name="mtproxy_prox_key_id_15755e_idx"),
        ),
        migrations.AlterField(
            model_name="proxyevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("install_started", "Install started"),
                    ("install_success", "Install success"),
                    ("install_failed", "Install failed"),
                    ("health_down", "Health down"),
                    ("health_up", "Health up"),
                    ("key_issued", "Key issued"),
                    ("key_reissued", "Key reissued"),
                    ("key_revoked", "Key revoked"),
                    ("abuse_flag", "Abuse flag"),
                ],
                max_length=64,
                verbose_name="Тип события",
            ),
        ),
    ]
