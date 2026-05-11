from django.apps import AppConfig

class OutlineForDenisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'outline_for_denis'
    verbose_name = 'Project configuration'

    def ready(self):
        from django.conf import settings

        engine = settings.DATABASES.get('default', {}).get('ENGINE')
        if engine != 'django.db.backends.sqlite3':
            return

        from django.db.backends.signals import connection_created

        def configure_sqlite(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA journal_mode=WAL;')
                cursor.execute('PRAGMA busy_timeout=30000;')

        connection_created.connect(configure_sqlite, dispatch_uid='outline_for_denis.sqlite_concurrency')
