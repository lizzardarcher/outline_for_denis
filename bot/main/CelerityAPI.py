import json
from urllib.parse import quote

import requests
from django.conf import settings


class CelerityAPI:
    """
    Клиент Management API панели C³ CELERITY (Hysteria 2 / Xray).

    Базовый URL в настройках должен указывать на префикс /api панели, например:
    https://dom-tunnel.ru/api

    Документация эндпоинтов: https://github.com/ClickDevTech/CELERITY-panel (раздел API Reference).
    """

    def __init__(self, timeout=15):
        raw = (getattr(settings, "C3CELERYTY_API_ENDPOINT", None) or "").strip()
        self.base_url = raw.rstrip("/")
        self.api_key = (getattr(settings, "C3CELERYTY_API_KEY", None) or "").strip()
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def _make_request(self, method, path, data=None, params=None):
        """
        Returns:
            tuple: (success: bool, body: dict | str | None) — как в MarzbanAPI.
        """
        if not self.base_url:
            return False, "C3CELERYTY_API_ENDPOINT is not set"
        if not self.api_key:
            return False, "C3CELERYTY_API_KEY is not set"

        url = self._url(path)
        try:
            response = requests.request(
                method,
                url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=self.timeout,
            )
            if response.status_code == 204:
                return True, None
            if 200 <= response.status_code < 300:
                try:
                    return True, response.json()
                except json.JSONDecodeError:
                    return True, response.text
            try:
                err_body = response.json()
            except json.JSONDecodeError:
                err_body = response.text
            return False, err_body
        except requests.exceptions.RequestException as e:
            return False, str(e)

    # --- Users (scopes users:read / users:write) ---

    def list_users(self, params=None):
        """GET /users — список пользователей (пагинация/фильтры через query params панели)."""
        return self._make_request("GET", "/users", params=params)

    def get_user(self, user_id: str):
        """GET /users/:userId"""
        uid = quote(str(user_id), safe="")
        return self._make_request("GET", f"/users/{uid}")

    def create_user(self, data: dict):
        """
        POST /users — тело запроса по модели User панели (userId, username, groups, nodes,
        trafficLimit, maxDevices, expireAt, enabled, …). См. README CELERITY-panel.
        """
        return self._make_request("POST", "/users", data=data)

    def update_user(self, user_id: str, data: dict):
        """PUT /users/:userId"""
        uid = quote(str(user_id), safe="")
        return self._make_request("PUT", f"/users/{uid}", data=data)

    def delete_user(self, user_id: str):
        """DELETE /users/:userId"""
        uid = quote(str(user_id), safe="")
        return self._make_request("DELETE", f"/users/{uid}")

    def enable_user(self, user_id: str):
        """POST /users/:userId/enable"""
        uid = quote(str(user_id), safe="")
        return self._make_request("POST", f"/users/{uid}/enable")

    def disable_user(self, user_id: str):
        """POST /users/:userId/disable"""
        uid = quote(str(user_id), safe="")
        return self._make_request("POST", f"/users/{uid}/disable")

    # --- Nodes (scopes nodes:read / nodes:write) ---

    def list_nodes(self, params=None):
        """GET /nodes"""
        return self._make_request("GET", "/nodes", params=params)

    def get_node(self, node_id: str):
        """GET /nodes/:id"""
        nid = quote(str(node_id), safe="")
        return self._make_request("GET", f"/nodes/{nid}")

    def create_node(self, data: dict):
        """
        POST /nodes — создание ноды (поля см. модель Node в README CELERITY-panel: type, name, ip, port, …).
        """
        return self._make_request("POST", "/nodes", data=data)

    def sync_node(self, node_id: str):
        """POST /nodes/:id/sync"""
        nid = quote(str(node_id), safe="")
        return self._make_request("POST", f"/nodes/{nid}/sync")

    # --- Группы серверов (scope stats:read) ---

    def list_groups(self, params=None):
        """GET /groups — список групп (ServerGroup)."""
        return self._make_request("GET", "/groups", params=params)

    @staticmethod
    def _extract_group_id(group_doc: dict):
        raw = group_doc.get("_id") or group_doc.get("id")
        if isinstance(raw, dict) and "$oid" in raw:
            return str(raw["$oid"])
        if raw is not None:
            return str(raw)
        return None

    @staticmethod
    def _normalize_groups_payload(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("groups", "data", "items", "results"):
                inner = data.get(key)
                if isinstance(inner, list):
                    return inner
        return []

    def find_group_id_by_name(
        self, name: str, case_insensitive: bool = True, *, groups_response=None
    ):
        """
        Ищет id группы по полю name в ответе GET /groups.

        Args:
            groups_response: если передан — не вызывается list_groups (уже полученный JSON).

        Returns:
            (True, group_id_str) или (False, error_message_or_response_body)
        """
        needle = (name or "").strip()
        if not needle:
            return False, "Пустое имя группы"

        if groups_response is not None:
            data = groups_response
        else:
            ok, data = self.list_groups()
            if not ok:
                return False, data

        groups = self._normalize_groups_payload(data)
        cmp_needle = needle.lower() if case_insensitive else needle

        for g in groups:
            if not isinstance(g, dict):
                continue
            gname = g.get("name") or g.get("title") or ""
            if case_insensitive:
                match = gname.strip().lower() == cmp_needle
            else:
                match = gname.strip() == needle
            if not match:
                continue
            gid = self._extract_group_id(g)
            if gid:
                return True, gid

        return False, f"Группа {needle!r} не найдена (всего записей: {len(groups)})"

    # --- Stats & sync ---

    def get_stats(self):
        """GET /stats — scope stats:read"""
        return self._make_request("GET", "/stats")

    def sync_all(self):
        """POST /sync — scope sync:write; синхронизация всех нод."""
        return self._make_request("POST", "/sync")

    def kick_user(self, user_id: str):
        """POST /kick/:userId — scope sync:write"""
        uid = quote(str(user_id), safe="")
        return self._make_request("POST", f"/kick/{uid}")

    # --- Подписки (без API key в README — токен в URL; для management пригодится info) ---

    def get_subscription_info(self, token: str):
        """GET /files/info/:token — метаданные подписки (трафик, срок)."""
        t = quote(str(token), safe="")
        return self._make_request("GET", f"/files/info/{t}")
