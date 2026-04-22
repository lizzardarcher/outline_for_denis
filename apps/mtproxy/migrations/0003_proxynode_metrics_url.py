from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mtproxy", "0002_abuse_score_and_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="proxynode",
            name="metrics_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="JSON endpoint метрик ноды (опционально). Пример: http://IP:9090/stats",
                max_length=1000,
                verbose_name="Metrics URL",
            ),
        ),
    ]
