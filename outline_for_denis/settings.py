import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')


DEBUG = True

ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS').split(',')

COOKIE_CONSENT_ENABLED = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Strict'
SECURE_CROSS_ORIGIN_OPENER_POLICY = "None"
# SESSION_COOKIE_SAMESITE = 'None'
# SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.mail.ru'
EMAIL_PORT = 2525
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = True
SERVER_EMAIL = EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

RECAPTCHA_PUBLIC_KEY = '6LckLMkqAAAAACzb0PZbvwxx1Js5OjwlgkG62TyG'
RECAPTCHA_PRIVATE_KEY = '6LckLMkqAAAAAIQzkTXJaGdCHwmQ051AoHe54jme'
RECAPTCHA_DEFAULT_LANGUAGE = 'ru'

SECURE_HSTS_SECONDS = 31536000  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True

# YOOKASSA_SHOP_ID=os.getenv('YOOKASSA_SHOP_ID_TEST')
# YOOKASSA_SECRET=os.getenv('YOOKASSA_SECRET_TEST')
YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID_LIVE')
YOOKASSA_SECRET = os.getenv('YOOKASSA_SECRET_LIVE')

YOOKASSA_PAYMENT_DESCRIPTION = 'Пополнение баланса пользователя'  # Описание платежа
YOOKASSA_SUCCESS_URL = 'https://domvpn.ru/dashboard/profile/'  # URL успеха
YOOKASSA_FAIL_URL = 'YOUR_FAIL_URL'  # URL неудачи

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_recaptcha',
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

# LOGIN_URL= '/auth/accounts/login/'