# Legacy Server columns (api_url, cert_sha256, is_activated, script_out) уже
# удалены из БД в 0028. Здесь только синхронизация состояния миграций — без DDL.

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("bot", "0028_server_hysteria_tls_meta"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="server",
                    name="api_url",
                ),
                migrations.RemoveField(
                    model_name="server",
                    name="cert_sha256",
                ),
                migrations.RemoveField(
                    model_name="server",
                    name="is_activated",
                ),
                migrations.RemoveField(
                    model_name="server",
                    name="script_out",
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    migrations.RunPython.noop,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
