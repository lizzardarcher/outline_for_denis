
import json

import requests
from django.conf import settings


# Теги inbounds должны совпадать с PasarGuard/Xray 1:1 (поле "tag" в xray config).
PASARGUARD_INBOUNDS_BY_PROTOCOL = {
    "outline": {
        "shadowsocks": ["Shadowsocks TCP"],
    },
    "vless": {
        "vless": ["VLESS TCP REALITY"],
    },
}


class PasarGuardAPI:
    """Клиент REST API панели PasarGuard (совместим с Marzban-style endpoints)."""

    def __init__(self):
        self.api_url = (getattr(settings, "PASARGUARD_API", None) or "").rstrip("/")
        self.api_token = self.get_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def get_access_token(self):
        username = (getattr(settings, "PASARGUARD_ADMIN_USERNAME", None) or "").strip()
        password = (getattr(settings, "PASARGUARD_ADMIN_PASSWORD", None) or "").strip()
        if not self.api_url or not username or not password:
            return None

        url = f"{self.api_url}/admin/token"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "",
            "client_id": "string",
            "client_secret": "string",
        }

        try:
            response = requests.post(url, headers=headers, data=data, timeout=12)
        except requests.exceptions.RequestException:
            return None

        if response.status_code == 200:
            return response.json().get("access_token")
        return None

    @staticmethod
    def inbounds_for_protocol(protocol):
        if protocol in PASARGUARD_INBOUNDS_BY_PROTOCOL:
            return PASARGUARD_INBOUNDS_BY_PROTOCOL[protocol]
        return {
            "vless": PASARGUARD_INBOUNDS_BY_PROTOCOL["vless"]["vless"],
            "shadowsocks": PASARGUARD_INBOUNDS_BY_PROTOCOL["outline"]["shadowsocks"],
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
        if not self.api_url:
            return False, "PASARGUARD_API is not set"
        if not self.api_token:
            return False, "Нет API-токена PasarGuard"

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

    def create_user(
        self,
        username,
        protocol=None,
        data_limit=0,
        expire=0,
        inbounds=None,
        proxies=None,
        status="active",
    ):
        data = {
            "data_limit": data_limit,
            "expire": expire,
            "inbounds": inbounds or self.inbounds_for_protocol(protocol),
            "proxies": proxies or {
                "vless": {"flow": "xtls-rprx-vision", "fp": "randomized", "fingerprint": "randomized"},
                "shadowsocks": {},
            },
            "status": status,
            "username": username,
        }
        return self._make_request("POST", "/user", data=data)

    def get_user(self, username):
        return self._make_request("GET", f"/user/{username}")

    def delete_user(self, username):
        return self._make_request("DELETE", f"/user/{username}")

    def list_users(self):
        return self._make_request("GET", "/users")

    def list_nodes(self):
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
        needle = (ip or "").strip()
        if not needle:
            return False, "Пустой ip"
        if not self.api_token:
            return False, "Нет API-токена PasarGuard"

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
            return False, f"Нода PasarGuard с ip={needle!r} не найдена"
        return True, node_ids

    def delete_node(self, node_id):
        if not self.api_token:
            return False, "Нет API-токена PasarGuard"
        return self._make_request("DELETE", f"/node/{int(node_id)}")

    def add_node(self, ip, name, port=62050):
        node = {
            "add_as_new_host": True,
            "address": ip,
            "api_port": 62051,
            "name": name,
            "port": port,
            "usage_coefficient": 1,
        }
        return self._make_request("POST", "/node", data=node)
