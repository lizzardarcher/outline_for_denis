import hashlib
import hmac

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import ObjectDoesNotExist

from bot.models import TelegramUser, UserProfile


class TelegramBackend(BaseBackend):
    """
    Вход через Telegram Login Widget.
    Telegram user id — только в TelegramUser.user_id; PK Django User — отдельный bigint.
    """

    def authenticate(self, request, data=None):
        if not data:
            return None

        User = get_user_model()

        try:
            telegram_api_user_id = int(data.get('id'))
            username = data.get('username') or ''
            first_name = data.get('first_name') or ''
            last_name = data.get('last_name') or ''
            photo_url = data.get('photo_url') or ''

            try:
                tg_user = TelegramUser.objects.get(user_id=telegram_api_user_id)
            except ObjectDoesNotExist:
                tg_user = TelegramUser.objects.create(
                    user_id=telegram_api_user_id,
                    username=username,
                    first_name=first_name or '—',
                    last_name=last_name,
                    photo_url=photo_url,
                    subscription_status=False,
                )

            try:
                profile = tg_user.user_profile
            except UserProfile.DoesNotExist:
                profile = None
            if profile is not None:
                return profile.user

            base_username = (
                (username or first_name or f"tg_{telegram_api_user_id}").strip()
                or f"tg_{telegram_api_user_id}"
            )
            django_username = base_username
            counter = 1
            while User.objects.filter(username=django_username).exists():
                django_username = f"{base_username}_{counter}"
                counter += 1

            user = User.objects.create_user(
                username=django_username,
                first_name=first_name,
                last_name=last_name,
                email='',
                password=User.objects.make_random_password(length=10),
            )

            try:
                orphan = UserProfile.objects.get(user=user)
            except UserProfile.DoesNotExist:
                UserProfile.objects.create(user=user, telegram_user=tg_user)
            else:
                orphan.telegram_user = tg_user
                orphan.save(update_fields=['telegram_user'])

            return user
        except Exception as e:
            messages.info(request, f"Error during telegram authentication: {e}")
            return None

    def check_telegram_data(self, data):
        """ Проверка подписи телеграм виджета. """
        data_check_string = '\n'.join(
            sorted(
                [f"{key}={value}" for key, value in data.items() if key != 'hash']
            )
        ).encode()
        secret_key = hashlib.sha256(settings.TELEGRAM_BOT_SECRET_KEY.encode()).digest()
        hmac_hash = hmac.new(secret_key, data_check_string, hashlib.sha256).hexdigest()

        if hmac_hash != data['hash']:
            raise Exception("Telegram data is invalid. Hashes doesn't match.")

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
