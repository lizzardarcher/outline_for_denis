import hashlib
import hmac
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import ObjectDoesNotExist

from bot.models import TelegramUser


class TelegramBackend(BaseBackend):
    def authenticate(self, request, data=None):
        print("TelegramBackend.authenticate called:", data)  # Добавьте это
        if not data:
            return None

        try:
            # Проверяем подлинность данных
            print("Checking data")
            self.check_telegram_data(data)

            user_id = int(data.get('id'))
            username = data.get('username')
            first_name = data.get('first_name')
            last_name = data.get('last_name')

            # Ищем пользователя в базе данных TelegramUser
            try:
                tg_user = TelegramUser.objects.get(user_id=user_id)
            except ObjectDoesNotExist:
                # Если пользователя нет, создаем
                tg_user = TelegramUser.objects.create(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name
                )

            # Пытаемся найти django пользователя. Если его нет, создаем.
            try:
                user = User.objects.get(username=user_id)
            except ObjectDoesNotExist:
                user = User.objects.create_user(
                    username=user_id,
                    first_name=first_name,
                    last_name=last_name,
                    password=User.objects.make_random_password(length=10),
                )

            return user  # Возвращаем django пользователя.
        except Exception as e:
            print(f"Error during telegram authentication: {e}")
            return None

    def check_telegram_data(self, data):
        print("TelegramBackend.check_telegram_data:", data)  # Добавьте это
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
