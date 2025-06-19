import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

# DEBUG = True
DEBUG = False

ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS').split(',')

COOKIE_CONSENT_ENABLED = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Strict'
SECURE_CROSS_ORIGIN_OPENER_POLICY = "None"

SECURE_HSTS_SECONDS = 31536000  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# SECURE_SSL_REDIRECT = True

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10240

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.mail.ru'
EMAIL_PORT = 2525
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = True
SERVER_EMAIL = EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

RECAPTCHA_PUBLIC_KEY = os.getenv('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = os.getenv('RECAPTCHA_PRIVATE_KEY')
RECAPTCHA_DEFAULT_LANGUAGE = 'ru'

YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID_LIVE')
YOOKASSA_SECRET = os.getenv('YOOKASSA_SECRET_LIVE')

YOOKASSA_SHOP_ID_BOT = os.getenv('YOOKASSA_SHOP_ID_BOT')
YOOKASSA_SECRET_BOT = os.getenv('YOOKASSA_SECRET_BOT')

YOOKASSA_SHOP_ID_SITE = os.getenv('YOOKASSA_SHOP_ID_SITE')
YOOKASSA_SECRET_SITE = os.getenv('YOOKASSA_SECRET_SITE')

YOOKASSA_PAYMENT_DESCRIPTION = 'Пополнение баланса пользователя'
YOOKASSA_SUCCESS_URL = 'https://dom-vpn.ru/dashboard/profile/'
YOOKASSA_FAIL_URL = 'YOUR_FAIL_URL'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_recaptcha',
    'django_celery_beat',
    'django_admin_inline_paginator',
    'fontawesomefree',
    'apps.authentication',
    'apps.home',
    'apps.dashboard',
    'apps.payment',
    'bot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'outline_for_denis.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

INTERNAL_IPS = ["127.0.0.1", ]
WSGI_APPLICATION = 'outline_for_denis.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

CELERY_BROKER_URL = 'redis://localhost:6379/0'       # URL Redis брокера
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'   # URL для хранения результатов задач Celery
CELERY_ACCEPT_CONTENT = ['application/json']         # Формат принимаемых сообщений
CELERY_TASK_SERIALIZER = 'json'                      # Сериализация задач
CELERY_RESULT_SERIALIZER = 'json'                    # Сериализация результатов
CELERY_TIMEZONE = 'UTC'                              # Часовой пояс
CELERY_TASK_TRACK_STARTED = True                     # Отслеживание состояния задач
CELERY_TASK_TIME_LIMIT = 30 * 60                     # Ограничение времени выполнения задачи (в секундах, 30 минут)

CELERY_ACKS_LATE = True                              # Подтверждение получения задачи после ее выполнения
CELERY_PREFETCH_MULTIPLIER = 1                       # Количество задач, получаемых воркером за раз
CELERYD_CONCURRENCY = 4                              # Количество процессов воркера

CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_MAX_LOOP_INTERVAL = 5                    # Проверять каждые 5 секунд

CELERY_TASK_ALWAYS_EAGER = True                      ### только для отладки

CELERY_IMPORTS = [
    'bot.tasks',
    'apps.payment.tasks',
]

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient"
        }
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = [
    'apps.authentication.auth_backends.TelegramBackend',
    'django.contrib.auth.backends.ModelBackend',
]

TELEGRAM_BOT_NAME = 'xDomvpn_Bot'
TELEGRAM_BOT_TOKEN = '7854367825:AAHSM0PyCf8RmUd4uMY7zBbCa1D3RzmlcyU'
TELEGRAM_BOT_SECRET_KEY = '872834723528358239'

LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'

STATIC_ROOT = os.path.join(BASE_DIR, "static")

MEDIA_URL = '/media/'

MEDIA_ROOT = os.path.join(BASE_DIR, "static/media")
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'staticfiles/'),
)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

KEY_LIMIT = 200
BOT_USERNAME = 'xDomvpn_Bot'
SUPPORT_ACCOUNT = 'Domvpnsupport'
# LOGIN_URL= '/auth/accounts/login/'
