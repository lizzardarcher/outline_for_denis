# Hysteria TLS meta на Server.
#
# SQLite: обычный AddField вызывает _remake_table и падает, если в БД осталась
# legacy-колонка script_out с невалидным JSON (CHECK JSON_VALID). Поэтому только
# SeparateDatabaseAndState + ALTER TABLE ADD COLUMN, предварительно чистим/удаляем legacy.

from django.db import migrations, models


LEGACY_SERVER_COLUMNS = (
    "api_url",
    "cert_sha256",
    "is_activated",
    "script_out",
)

HYSTERIA_SERVER_COLUMNS_SQLITE = (
    ("hysteria_tls_sni", "varchar(255) NOT NULL DEFAULT ''"),
    ("hysteria_pin_sha256", "varchar(64) NOT NULL DEFAULT ''"),
    ("hysteria_cert_synced_at", "datetime NULL"),
)


def _table_column_names(schema_editor, table):
    conn = schema_editor.connection
    with conn.cursor() as cursor:
        desc = conn.introspection.get_table_description(cursor, table)
    return {row.name for row in desc}


def _forwards_add_hysteria_tls_meta(apps, schema_editor):
    Server = apps.get_model("bot", "Server")
    table = Server._meta.db_table
    conn = schema_editor.connection
    vendor = conn.vendor

    try:
        existing = _table_column_names(schema_editor, table)
    except Exception:
        return

    qtable = conn.ops.quote_name(table)
    with conn.cursor() as cursor:
        if "script_out" in existing and vendor == "sqlite":
            cursor.execute(
                f"UPDATE {qtable} SET script_out = NULL "
                f"WHERE script_out IS NOT NULL "
                f"AND NOT json_valid(script_out)"
            )

        for col in LEGACY_SERVER_COLUMNS:
            if col not in existing:
                continue
            qcol = conn.ops.quote_name(col)
            if vendor == "postgresql":
                cursor.execute(
                    f"ALTER TABLE {qtable} DROP COLUMN IF EXISTS {qcol}"
                )
            elif vendor == "sqlite":
                cursor.execute(f"ALTER TABLE {qtable} DROP COLUMN {qcol}")
            elif vendor == "mysql":
                cursor.execute(f"ALTER TABLE {qtable} DROP COLUMN {qcol}")
            else:
                cursor.execute(
                    f"ALTER TABLE {qtable} DROP COLUMN IF EXISTS {qcol}"
                )
            existing.discard(col)

        if vendor == "sqlite":
            for col_name, col_def in HYSTERIA_SERVER_COLUMNS_SQLITE:
                if col_name in existing:
                    continue
                qcol = conn.ops.quote_name(col_name)
                cursor.execute(
                    f"ALTER TABLE {qtable} ADD COLUMN {qcol} {col_def}"
                )
        elif vendor == "postgresql":
            adds = [
                (
                    "hysteria_tls_sni",
                    "varchar(255) NOT NULL DEFAULT ''",
                ),
                (
                    "hysteria_pin_sha256",
                    "varchar(64) NOT NULL DEFAULT ''",
                ),
                (
                    "hysteria_cert_synced_at",
                    "timestamp with time zone NULL",
                ),
            ]
            for col_name, col_def in adds:
                if col_name in existing:
                    continue
                qcol = conn.ops.quote_name(col_name)
                cursor.execute(
                    f"ALTER TABLE {qtable} ADD COLUMN IF NOT EXISTS {qcol} {col_def}"
                )
        else:
            for col_name, field in (
                ("hysteria_tls_sni", "varchar(255) NOT NULL DEFAULT ''"),
                ("hysteria_pin_sha256", "varchar(64) NOT NULL DEFAULT ''"),
                ("hysteria_cert_synced_at", "datetime NULL"),
            ):
                if col_name in existing:
                    continue
                qcol = conn.ops.quote_name(col_name)
                cursor.execute(
                    f"ALTER TABLE {qtable} ADD COLUMN {qcol} {field}"
                )


class Migration(migrations.Migration):

    dependencies = [
        ("bot", "0027_telegrammessage_cancelled_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="server",
                    name="hysteria_tls_sni",
                    field=models.CharField(
                        blank=True,
                        default="",
                        help_text="CN из /etc/hysteria/cert.pem (для Happ и клиентов без insecure=1).",
                        max_length=255,
                        verbose_name="Hysteria TLS SNI",
                    ),
                ),
                migrations.AddField(
                    model_name="server",
                    name="hysteria_pin_sha256",
                    field=models.CharField(
                        blank=True,
                        default="",
                        help_text="SHA-256 fingerprint cert.pem, hex без двоеточий.",
                        max_length=64,
                        verbose_name="Hysteria pinSHA256",
                    ),
                ),
                migrations.AddField(
                    model_name="server",
                    name="hysteria_cert_synced_at",
                    field=models.DateTimeField(
                        blank=True,
                        help_text="Когда последний раз снимали pin/SNI по SSH.",
                        null=True,
                        verbose_name="Hysteria cert sync",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    _forwards_add_hysteria_tls_meta,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
