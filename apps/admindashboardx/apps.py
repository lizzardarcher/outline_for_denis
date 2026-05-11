from django.apps import AppConfig

class AuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.admindashboardx'

    def ready(self):
        # noqa: F401 — регистрация сигналов инвалидации кэша
        import apps.admindashboardx.signals  # noqa: F401


