from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mtproxy", "0003_proxynode_metrics_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="proxynode",
            name="manage_api_token",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Bearer token для manage API (опционально).",
                max_length=1000,
                verbose_name="Manage API token",
            ),
        ),
        migrations.AddField(
            model_name="proxynode",
            name="manage_api_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Endpoint управления секретами ноды (опционально). Пример: http://IP:9090/manage",
                max_length=1000,
                verbose_name="Manage API URL",
            ),
        ),
    ]
