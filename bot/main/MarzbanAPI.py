import requests
import json

from django.conf import settings

from bot.main import django_orm
from bot.models import TelegramBot


class MarzbanAPI:
    """
    Класс для взаимодействия с API Marzban для управления пользователями.
    """

    def __init__(self):
        """
        Инициализирует экземпляр класса.

        Args:
            api_url (str): URL API Marzban.
            api_token (str): Токен API для аутентификации.
        """

        self.api_url = settings.MARZBAN_API
        self.api_token = self.get_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def get_access_token(self):
        _username = TelegramBot.objects.all().first().vless_unane
        _password = TelegramBot.objects.all().first().vless_pwd
        url = 'https://mvless.ru/api/admin/token'
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'grant_type': 'password',
            'username': _username,
            'password': _password,
            'scope': '',
            'client_id': 'string',
            'client_secret': 'string'
        }

        response = requests.post(url, headers=headers, data=data)

        if response.status_code == 200:
            # Если запрос успешен, возвращаем access_token
            return response.json().get('access_token')
        else:
            # Если произошла ошибка, выводим сообщение
            print(f"Error: {response.status_code}, {response.text}")
            return None

    def _make_request(self, method, endpoint, data=None):
        """
        Вспомогательная функция для выполнения HTTP-запросов.

        Args:
            method (str): HTTP-метод (например, "GET", "POST", "DELETE").
            endpoint (str): Конечная точка API (например, "/users").
            data (dict, optional): Данные для отправки в теле запроса (для POST, PUT). Defaults to None.

        Returns:
            tuple: (bool, dict) -  (Успешно ли выполнен запрос, данные ответа или сообщение об ошибке)
                   Возвращает (True, data) в случае успеха и (False, error_message) в случае неудачи.
        """
        url = f"{self.api_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, json=data, timeout=10)  # Добавил timeout

            response.raise_for_status()

            if response.status_code == 204:
                return True, None
            try:
                return True, response.json()
            except json.JSONDecodeError:
                return True, response.text
        except requests.exceptions.RequestException as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

    def create_user(self, username, data_limit=0, data_limit_reset_strategy="no_reset", expire=0,
                    inbounds=None, next_plan=None, note="", on_hold_expire_duration=0,
                    on_hold_timeout=None, proxies=None, status="active"):
        """
        Создает нового пользователя Marzban с заданными параметрами.

        Args:
            username (str): Имя пользователя.
            data_limit (int): Лимит данных в байтах (0 = без лимита).
            data_limit_reset_strategy (str): Стратегия сброса лимита данных ("no_reset", "daily", "monthly" и т.д.).
            expire (int): Время истечения срока действия в секундах (0 = без истечения срока действия).
            inbounds (dict, optional):  Словари с настройками входящих подключений. Defaults to None.
            next_plan (dict, optional):  Словари с настройками следующего плана. Defaults to None.
            note (str, optional): Заметка. Defaults to "".
            on_hold_expire_duration (int, optional): Продолжительность удержания в секундах. Defaults to 0.
            on_hold_timeout (str, optional):  Время удержания (ISO 8601). Defaults to None.
            proxies (dict, optional): Словари с настройками прокси. Defaults to None.
            status (str, optional): Статус пользователя ("active", "inactive"). Defaults to "active".


        Returns:
            tuple: (bool, dict) - (Успешно ли создан пользователь, данные пользователя или сообщение об ошибке)
        """

        data = {
            "data_limit": data_limit,
            "expire": expire,
            "inbounds": {
                "vless": ["VLESS XHTTP REALITY"],
                "shadowsocks": ["Shadowsocks TCP"]
            },
            "proxies": proxies or {
                "vless": {},
                "shadowsocks": {}
            },
            "status": status,
            "username": username
        }

        success, result = self._make_request("POST", "/user", data=data)
        return success, result

    def get_user(self, username):
        """
        Получает информацию о пользователе.

        Args:
            username (str): Имя пользователя.

        Returns:
            tuple: (bool, dict) - (Успешно ли получена информация, данные пользователя или сообщение об ошибке)
        """
        success, result = self._make_request("GET", f"/user/{username}")
        return success, result

    def delete_user(self, username):
        """
        Удаляет пользователя.

        Args:
            username (str): Имя пользователя.

        Returns:
            tuple: (bool, dict) - (Успешно ли удален пользователь, None или сообщение об ошибке)
        """
        success, result = self._make_request("DELETE", f"/user/{username}")
        return success, result

    def list_users(self):
        """
        Получает список всех пользователей.

        Returns:
            tuple: (bool, list) - (Успешно ли получен список, список пользователей или сообщение об ошибке)
        """
        success, result = self._make_request("GET", "/users")
        return success, result

    def add_node(self, ip, name, port=62050):
        node = {
            "add_as_new_host": True,
            "address": ip,
            "api_port": 62051,
            "name": name,
            "port": port,
            "usage_coefficient": 1
        }
        print(self.api_token)
        success, result = self._make_request("POST", f"/node", data=node)
        return success, result

