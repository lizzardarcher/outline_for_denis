import requests
import json

from django.conf import settings

from bot.models import TelegramBot


# Теги inbounds должны совпадать с Marzban/Xray 1:1 (поле "tag" в xray config).
MARZBAN_INBOUNDS_BY_PROTOCOL = {
    "outline": {
        "shadowsocks": ["Shadowsocks TCP"],
    },
    "vless": {
        "vless": ["VLESS XHTTP REALITY"],
    },
}


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
        bot = TelegramBot.objects.all().first()
        if not bot or not bot.vless_unane or not bot.vless_pwd:
            return None
        _username = bot.vless_unane
        _password = bot.vless_pwd
        url = f'{settings.MARZBAN_API}/admin/token'
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

        response = requests.post(url, headers=headers, data=data, timeout=12)

        if response.status_code == 200:
            # Если запрос успешен, возвращаем access_token
            return response.json().get('access_token')
        else:
            # Если произошла ошибка, выводим сообщение
            print(f"Error: {response.status_code}, {response.text}")
            return None

    @staticmethod
    def inbounds_for_protocol(protocol):
        if protocol in MARZBAN_INBOUNDS_BY_PROTOCOL:
            return MARZBAN_INBOUNDS_BY_PROTOCOL[protocol]
        return {
            "vless": MARZBAN_INBOUNDS_BY_PROTOCOL["vless"]["vless"],
            "shadowsocks": MARZBAN_INBOUNDS_BY_PROTOCOL["outline"]["shadowsocks"],
        }

    @staticmethod
    def _error_detail(response, request_data=None):
        body = response.text
        try:
            body = response.json()
        except json.JSONDecodeError:
            pass
        detail = {
            "status_code": response.status_code,
            "reason": response.reason,
            "url": response.url,
            "body": body,
        }
        if request_data is not None:
            detail["request_data"] = request_data
        return detail

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
            response = requests.request(method, url, headers=self.headers, json=data, timeout=10)

            if response.status_code >= 400:
                return False, self._error_detail(response, request_data=data)

            if response.status_code == 204:
                return True, None
            try:
                return True, response.json()
            except json.JSONDecodeError:
                return True, response.text
        except requests.exceptions.RequestException as e:
            resp = getattr(e, "response", None)
            if resp is not None:
                return False, self._error_detail(resp, request_data=data)
            return False, {"error": "request_error", "message": str(e)}
        except Exception as e:
            return False, {"error": "unexpected_error", "message": str(e)}

    def create_user(self, username, protocol=None, data_limit=0, data_limit_reset_strategy="no_reset", expire=0,
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
            "inbounds": inbounds or self.inbounds_for_protocol(protocol),
            "proxies": proxies or {
                "vless": {"flow": "xtls-rprx-vision", "fp": "randomized", "fingerprint": "randomized"},
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

    def list_nodes(self):
        """
        GET /nodes — список нод Marzban.

        Returns:
            tuple: (bool, list | str) — успех и список нод или сообщение об ошибке.
        """
        success, result = self._make_request("GET", "/nodes")
        if not success:
            return False, result
        if isinstance(result, list):
            return True, result
        if isinstance(result, dict):
            for key in ("nodes", "items", "data"):
                inner = result.get(key)
                if isinstance(inner, list):
                    return True, inner
        return False, f"Неожиданный ответ list_nodes: {type(result).__name__}"

    def find_node_ids_by_ip(self, ip: str):
        """
        Ищет id нод Marzban по IP (поле address).

        Returns:
            tuple: (bool, list[int] | str)
        """
        needle = (ip or "").strip()
        if not needle:
            return False, "Пустой ip"
        if not self.api_token:
            return False, "Нет API-токена Marzban"

        ok, data = self.list_nodes()
        if not ok:
            return False, data

        node_ids = []
        for item in data:
            if not isinstance(item, dict):
                continue
            addr = str(item.get("address") or item.get("ip") or "").strip()
            if addr != needle:
                continue
            raw_id = item.get("id")
            if raw_id is not None:
                node_ids.append(int(raw_id))
        if not node_ids:
            return False, f"Нода Marzban с ip={needle!r} не найдена"
        return True, node_ids

    def delete_node(self, node_id):
        """
        DELETE /node/:node_id — удаление ноды из Marzban.

        Returns:
            tuple: (bool, None | str)
        """
        if not self.api_token:
            return False, "Нет API-токена Marzban"
        return self._make_request("DELETE", f"/node/{int(node_id)}")

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

