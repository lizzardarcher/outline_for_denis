from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot", "0029_remove_server_api_url_remove_server_cert_sha256_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="server",
            name="is_pasarguard_activated",
            field=models.BooleanField(
                default=False,
                editable=True,
                help_text="Нода marzban-node зарегистрирована в панели PasarGuard и готова к выдаче ключей.",
                verbose_name="PasarGuard",
            ),
        ),
    ]
