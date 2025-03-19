import os
from datetime import datetime, timedelta

import requests
import json
import uuid
import dotenv

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
            api_url (str): URL API Marzban (например, "https://your-marzban-domain.com/api/").  Обязательно укажите '/api/' в конце!
            api_token (str): Токен API для аутентификации.
        """
        self.api_url = "https://mvless.ru/api"
        self.api_token = TelegramBot.objects.all().first().marzban_api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

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

            response.raise_for_status()  # Поднимает HTTPError для плохих ответов (4xx или 5xx)

            if response.status_code == 204:  # No content
                return True, None  # Успешный DELETE часто возвращает 204
            try:
                return True, response.json()
            except json.JSONDecodeError:
                return True, response.text  # Возвращаем текст, если JSON не декодируется
        except requests.exceptions.RequestException as e:
            return False, str(e)  # Обрабатываем ошибки соединения, таймауты и т.д.
        except Exception as e:
            return False, str(e)  # Обрабатываем любые другие исключения

    def create_user(self, username, data_limit=1024 * 1024 * 1024 * 300, data_limit_reset_strategy="no_reset", expire=0,
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
                "vless": ["VLESS TCP REALITY"],
            },
            # "next_plan": {
            #     "add_remaining_traffic": False,
            #     "data_limit": 0,
            #     "expire": 0,
            #     "fire_on_either": True
            # },
            # "note": note,
            # "on_hold_expire_duration": on_hold_expire_duration,
            # "on_hold_timeout": on_hold_timeout,
            "proxies": proxies or {
                "vless": {},
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
        success, result = self._make_request("POST", f"/node", data=node)
        return success, result

# Пример использования:
# if __name__ == '__main__':
#     marzban = MarzbanAPI()
#     marzban.add_node("178.208.78.170", "test")
# #
# #     # Замените на свои значения
#     API_URL = "https://mvless.ru/api"
#     API_TOKEN = TelegramBot.objects.all().first().marzban_api_key
#
#
#     marzban = MarzbanAPI(API_URL, API_TOKEN)
# # Пример создания пользователя с настройками
# success, result = marzban.create_user(
#     username="testuser22212",
#     data_limit_reset_strategy="monthly",
#     # expire=int(round(datetime.now().timestamp() + (60 * 60 * 24 * 30))),  # 30 дней
#     proxies={
#         "vless": {
#             "id": str(uuid.uuid4())
#         }
#     },
# )
#
# if success:
#     print("Пользователь создан:", result)
# else:
#     print("Ошибка создания пользователя:", result)


# # Получение информации о пользователе
# success, result = marzban.get_user("baby3")
# if success:
#     print("Информация о пользователе:", result)
#     print("Link:", result["links"][0].split("#")[0] + "#VLESS 🇳🇱")
# else:
#     print("Ошибка получения информации о пользователе:", result)


# # Получение конфигурации пользователя
# success, result = marzban.get_user_configuration("testuser", "sing-box")
# if success:
#     print("Конфигурация пользователя:\n", result)  # Возможно, потребуется дополнительная обработка для форматирования
# else:
#     print("Ошибка получения конфигурации:", result)


# # Список пользователей
# success, result = marzban.list_users()
# if success:
#     print("Список пользователей:", result)
# else:
#     print("Ошибка получения списка пользователей:", result)


# # Удаление пользователя
# success, result = marzban.delete_user("ansel")
# if success:
#     print("Пользователь удален")
# else:
#     print("Ошибка удаления пользователя:", result)
