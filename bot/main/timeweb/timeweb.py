import requests
import json
import os


class TimeWeb:
    """

    """

    def __init__(self, token: str, headers: dict):
        self.token = token
        self.headers = headers

    def get_finances(self) -> dict:
        """
        Получение платежной информации
        :return: Объект JSON с ключом finances
        """
        response = requests.get(url='https://api.timeweb.cloud/api/v1/account/finances', headers=self.headers)
        return response.json()

    def get_servers(self) -> dict:
        """
        Получение списка серверов
        :return: Объект JSON с ключом servers
        """
        response = requests.get(url='https://api.timeweb.cloud/api/v1/servers', headers=self.headers)
        return response.json()

    def get_servers_os(self) -> dict:
        """
        Получение списка OS
        :return: Объект JSON с ключом servers
        """

        response = requests.get(url='https://api.timeweb.cloud/api/v1/os/servers', headers=self.headers)
        return response.json()

    def get_servers_software(self) -> dict:
        """
        Получение списка ПО из маркетплейса
        :return: Объект JSON с ключом servers
        """
        response = requests.get(url='https://api.timeweb.cloud/api/v1/software/servers', headers=self.headers)
        return response.json()

    def get_server(self, server_id: str) -> dict:
        """
        Получение сервера
        :return: Объект JSON с ключом server
        """
        response = requests.get(url=f'https://api.timeweb.cloud/api/v1/servers/{server_id}', headers=self.headers)
        return response.json()

    def create_server(self, json_data: dict):
        """
        Создание сервера
        Cервер будет создан с использованием предоставленной информации. Тело ответа будет содержать объект JSON с информацией о созданном сервере
        :return: Объект JSON с ключом servers
        """
        response = requests.post(url='https://api.timeweb.cloud/api/v1/servers', headers=self.headers, json=json_data)
        return response.json()

    def delete_server(self, server_id: str) -> dict:
        """
        Удаление сервера
        Обратите внимание, если на аккаунте включено удаление серверов по смс, то вернется ошибка 423.
        :param server_id:
        :return: Объект JSON с ключом server_delete
        """
        response = requests.delete(url=f'https://api.timeweb.cloud/api/v1/servers/{server_id}', headers=self.headers)
        return response.json()
