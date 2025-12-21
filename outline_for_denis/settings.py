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
DOMAIN = CSRF_TRUSTED_ORIGINS[0]

COOKIE_CONSENT_ENABLED = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Strict'
SECURE_CROSS_ORIGIN_OPENER_POLICY = "None"

SECURE_HSTS_SECONDS = 31536000  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10240

# Email настройки для Gmail
# https://myaccount.google.com/apppasswords
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
PASSWORD_RESET_TIMEOUT = 3600  # Токен действует 1 час
EMAIL_TIMEOUT = 30
EMAIL_USE_LOCALTIME = True

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
    'jazzmin',
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


JAZZMIN_SETTINGS = {
    "site_header": "DOMVPNAdmin",
    "site_logo": "img/favicon.png",
    "login_logo": "img/favicon.png",
    "login_logo_dark": "img/favicon.png",
    "site_logo_classes": "img-square",
    "site_icon": None,
    "welcome_sign": "Welcome to the DOMVPNAdmin",
    "copyright": "DOMVPNAdmin",


    "search_model": ["bot.TelegramUser"],

    "topmenu_links": [

        {"model": "bot.Server"},
        {"model": "bot.TelegramMessage"},
        {"model": "bot.Logging"},

    ],

    "show_sidebar": True,

    "navigation_expanded": True,

    "hide_apps": [],

    "hide_models": ["bot.UserProfile"],

    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "bot.Logging": "fa-regular fa-font-awesome",

        "bot.TelegramBot": "fa-solid fa-robot",
        "bot.TelegramMessage": "fa-solid fa-paper-plane",
        "bot.TelegramUser": "fa-solid fa-user",
        "bot.Server": "fa-solid fa-server",
        "bot.VpnKey": "fa-solid fa-key",
        "bot.Country": "fa-solid fa-globe",

        "bot.ReferralSettings": "fa-solid fa-gears",
        "bot.TelegramReferral": "fa-solid fa-people-arrows",
        "bot.ReferralTransaction": "fa-solid fa-genderless",

        "bot.Transaction": "fa-solid fa-money-check-dollar",
        "bot.IncomeInfo": "fa-solid fa-coins",
        "bot.Prices": "fa-solid fa-tag",
        "bot.WithdrawalRequest": "fa-solid fa-bell",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",

    "related_modal_active": False,


    "custom_css": None,
    "custom_js": None,
    "use_google_fonts_cdn": True,
    "show_ui_builder": True,

    # Render out the change view as a single form, or in tabs, current options are
    # - single
    # - horizontal_tabs (default)
    # - vertical_tabs
    # - collapsible
    # - carousel
    # "changeform_format": "carousel",
    # override change forms on a per modeladmin basis
    # "changeform_format_overrides": {"auth.user": "collapsible", "auth.group": "vertical_tabs"},
    # Add a language dropdown into the admin
    # "language_chooser": True,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    # "accent": "accent-primary",
    "accent": "accent-light",
    "navbar": "navbar-primary navbar-dark",
    "no_navbar_border": False,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": False,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    "theme": "cyborg",
    "dark_mode_theme": "darkly",
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    }
}
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

CELERY_BROKER_URL = 'redis://localhost:6379/0'  # URL Redis брокера
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'  # URL для хранения результатов задач Celery
CELERY_ACCEPT_CONTENT = ['application/json']  # Формат принимаемых сообщений
CELERY_TASK_SERIALIZER = 'json'  # Сериализация задач
CELERY_RESULT_SERIALIZER = 'json'  # Сериализация результатов
CELERY_TIMEZONE = 'UTC'  # Часовой пояс
CELERY_TASK_TRACK_STARTED = True  # Отслеживание состояния задач
CELERY_TASK_TIME_LIMIT = 30 * 60  # Ограничение времени выполнения задачи (в секундах, 30 минут)

CELERY_ACKS_LATE = True  # Подтверждение получения задачи после ее выполнения
CELERY_PREFETCH_MULTIPLIER = 1  # Количество задач, получаемых воркером за раз
CELERYD_CONCURRENCY = 4  # Количество процессов воркера

CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_MAX_LOOP_INTERVAL = 5  # Проверять каждые 5 секунд

CELERY_TASK_ALWAYS_EAGER = True  ### только для отладки

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
DEV_ACCOUNT = 'megafoll'

# LOGIN_URL= '/auth/accounts/login/'
