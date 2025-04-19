import hashlib
import hmac
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import ObjectDoesNotExist

from bot.models import TelegramUser, UserProfile


class TelegramBackend(BaseBackend):
    def authenticate(self, request, data=None):
        if not data:
            return None

        try:
            user_id = int(data.get('id'))
            username = data.get('username') or ''
            first_name = data.get('first_name') or ''
            last_name = data.get('last_name') or ''
            photo_url = data.get('photo_url') or ''

            try:
                tg_user = TelegramUser.objects.get(user_id=user_id)
            except ObjectDoesNotExist as e:
                tg_user = TelegramUser.objects.create(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    photo_url=photo_url,
                    subscription_status=False,
                )

            try:
                user = User.objects.get(id=user_id)
            except ObjectDoesNotExist as e:
                user = User.objects.create_user(
                    id=user_id,
                    username=username or first_name,
                    first_name=first_name,
                    last_name=last_name,
                    password=User.objects.make_random_password(length=10),
                )

            try:
                profile = UserProfile.objects.get(user=user)
            except ObjectDoesNotExist as e:
                profile = UserProfile.objects.create(user=user, telegram_user=tg_user)
            else:
                profile.telegram_user = tg_user
                profile.save()

            return user  # Возвращаем django пользователя.
        except Exception as e:
            messages.info(request,f"Error during telegram authentication: {e}")
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
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
