
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admindashboardx", "0005_server_health_beat"),
    ]

    operations = [
        migrations.AddField(
            model_name="serverhealthsample",
            name="chebur_status",
            field=models.CharField(blank=True, default="", max_length=16, verbose_name="Статус Cheburcheck"),
        ),
        migrations.AddField(
            model_name="serverhealthsample",
            name="chebur_detail",
            field=models.CharField(blank=True, default="", max_length=300, verbose_name="Детали Cheburcheck"),
        ),
        migrations.AlterField(
            model_name="serverhealthstate",
            name="channel",
            field=models.CharField(
                choices=[("panel", "Панели"), ("ping", "Сеть"), ("chebur", "Cheburcheck")],
                max_length=16,
                verbose_name="Канал",
            ),
        ),
    ]
