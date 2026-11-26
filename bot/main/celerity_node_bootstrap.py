"""
Celerity (C³): создание ноды в панели (POST /nodes при необходимости) и установка ПО (setup).
Используется Celery-task'ами; без sys.exit и без print (ошибки — в возвращаемом значении).
"""
from __future__ import annotations

import json
import re

import time

import secrets
from typing import Any, Callable, Optional, Tuple

from django.conf import settings

from bot.main.CelerityAPI import CelerityAPI
from bot.main.celerity_key_issue import _celerity_group_id
from bot.main.celerity_panel_form import save_node_obfs_via_panel
from bot.main.hysteria_tls_meta import (
    save_hysteria_tls_meta_to_server,
    try_sync_hysteria_tls_meta_after_setup,
)
from bot.main.node_firewall import hysteria_service_root_snippet
from bot.models import Server

_SERVER_PASSWORD_PLACEHOLDERS = frozenset(("", "<PASSWORD>"))
_DEFAULT_HYSTERIA_SNI = "bing.com"
_PIN_LINE = re.compile(r"HYSTERIA_PIN_SHA256=([0-9A-Fa-f]{64})")


_OBFS_SALAMANDER_LINE = re.compile(
    r"(?im)^\s*type:\s*[\"']?salamander[\"']?\s*(?:#.*)?$"
)

# Второй setup запускается, когда cert.pem уже есть. Скрипт идёт до
# перезапуска: снова кладёт drop-in User=root и печатает pin.
# Первая установка pin снять не может — сертификат появляется после initScript.
HYSTERIA_PIN_INIT_SCRIPT = hysteria_service_root_snippet() + """
if [ -f /etc/hysteria/key.pem ] && [ -r /etc/hysteria/key.pem ]; then
  echo "HYSTERIA_KEY_READABLE"
else
  echo "HYSTERIA_KEY_NOT_READABLE"
  ls -la /etc/hysteria >&2 || true
fi
if [ -f /etc/hysteria/cert.pem ]; then
  pin="$(openssl x509 -in /etc/hysteria/cert.pem -outform DER | sha256sum | awk '{print $1}')"
  echo "HYSTERIA_PIN_SHA256=${pin}"
else
  echo "HYSTERIA_CERT_MISSING"
fi
"""


def new_salamander_password() -> str:
    """16 символов, как просили для obfs. В лог этот пароль не пишется."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def _flag_from_country_name_for_app(name: Optional[str]) -> str:
    if not name:
        return ""
    s = name.rstrip()
    if not s:
        return ""
    if len(s) >= 2:
        o2, o1 = ord(s[-2]), ord(s[-1])
        if 0x1F1E6 <= o2 <= 0x1F1FF and 0x1F1E6 <= o1 <= 0x1F1FF:
            return s[-2:]
    return s[-1]


def _flag_emoji_for_server(server: Server) -> str:
    country = getattr(server, "country", None)
    if country is None:
        return ""
    return _flag_from_country_name_for_app(
        getattr(country, "name_for_app", None) or ""
    )


def resolve_celerity_node_sni() -> str:
    """SNI маскировки Hysteria. Пустая настройка — bing.com."""
    raw = getattr(settings, "CELERITY_NODE_SNI", None)
    sni = str(raw).strip() if raw else ""
    return sni or _DEFAULT_HYSTERIA_SNI


def django_ssh_looks_weak(server: Server) -> bool:
    pwd = (server.password or "").strip()
    return not pwd or pwd in _SERVER_PASSWORD_PLACEHOLDERS


def build_celerity_node_payload(
    server: Server,
    group_id: str,
    node_type: str,
    obfs_password: str = "",
) -> dict:
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("У Server пустой ip_address")
    name = (server.hosting or "").strip() or f"server-{server.pk}-{ip}"

    ssh_user = (server.user or "root").strip() or "root"
    ssh_password = (server.password or "").strip()
    key_pem = (getattr(settings, "CELERITY_SSH_PRIVATE_KEY", None) or "").strip()

    if ssh_password in _SERVER_PASSWORD_PLACEHOLDERS:
        ssh_password = ""
    if not ssh_password and not key_pem:
        raise ValueError(
            f"Нужен SSH пароль в Server.password или PEM в CELERITY_SSH_PRIVATE_KEY (pk={server.pk})"
        )

    ssh_obj: dict = {
        "port": int(getattr(settings, "CELERITY_SSH_PORT", None) or 22),
        "username": ssh_user,
    }
    if ssh_password:
        ssh_obj["password"] = ssh_password
    if key_pem:
        ssh_obj["privateKey"] = key_pem

    flag = _flag_emoji_for_server(server)

    body: dict = {
        "type": node_type,
        "name": name,
        "ip": ip,
        "port": int(getattr(settings, "CELERITY_NODE_PORT", None) or 443),
        "groups": [group_id],
        "ssh": ssh_obj,
    }
    if flag:
        body["flag"] = flag
    # domain включает ACME в панели и сертификат перестаёт быть self-signed CN=bing.com.
    dom = (getattr(settings, "CELERITY_NODE_DOMAIN", None) or "").strip()
    if dom:
        body["domain"] = dom
    body["sni"] = resolve_celerity_node_sni()
    if obfs_password:
        # Документация ноды: obfs { type, password } в том же теле, что и нода.
        # Диапазон без дефиса: скрипт прыжков панели тогда пустой и не зовёт iptables.
        body["obfs"] = {"type": "salamander", "password": obfs_password}
        body["portRange"] = "443"
        body["subscriptionVariants"] = "tls"
    return body


def create_celerity_node_or_find(
    api: CelerityAPI,
    server: Server,
    group_id: str,
    node_type: str,
    ip: str,
    obfs_password: str = "",
) -> Tuple[bool, str, Any]:
    try:
        body = build_celerity_node_payload(
            server, group_id, node_type, obfs_password=obfs_password
        )
    except ValueError as e:
        return False, "", str(e)

    ok_c, res_c = api.create_node(body)
    if ok_c and isinstance(res_c, dict):
        nid = CelerityAPI._extract_group_id(res_c)
        if nid:
            return True, nid, None
        ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
        if ok_f:
            return True, nid2, None
        return False, "", "create OK, но нет _id в ответе и find не удался"

    err_text = res_c
    if isinstance(res_c, dict):
        err_text = res_c.get("error", res_c)
        if isinstance(err_text, str) and "already exists" in err_text.lower():
            ok_f, nid2 = api.find_node_id_by_ip(ip, node_type)
            if ok_f:
                return True, nid2, None
            return False, "", f"duplicate but find failed: {nid2!r}"

    return False, "", res_c

def flatten_setup_logs(data: Any) -> str:
    if isinstance(data, dict):
        logs = data.get("logs")
        if isinstance(logs, list):
            return "\n".join(str(item) for item in logs)
        if isinstance(logs, str):
            return logs
    return "" if data is None else str(data)


def pin_sha256_from_setup_logs(data: Any) -> str:
    match = _PIN_LINE.search(flatten_setup_logs(data))
    return match.group(1).upper() if match else ""


def ensure_celerity_node_sni(api: CelerityAPI, node_id: str, sni: str) -> Tuple[bool, Any]:
    """PUT только sni: панель не затирает ssh и остальные поля."""
    return api.update_node(node_id, {"sni": sni})


def mark_server_c3_activated(server: Server) -> None:
    server.is_c3celeryty_activated = True
    server.save(update_fields=["is_c3celeryty_activated"])


def remember_hysteria_sni(server: Server, sni: str, emit: Optional[Callable[[str, str], None]] = None) -> bool:
    """Пишет SNI в Server сразу, не дожидаясь pin. Пустой pin при этом не затирает."""
    sni = (sni or "").strip()
    if not sni:
        return False
    server.hysteria_tls_sni = sni
    save = getattr(server, "save", None)
    if not callable(save):
        return True
    try:
        save(update_fields=["hysteria_tls_sni"])
    except Exception as exc:
        if emit:
            emit("ERROR", f"Не удалось записать Hysteria TLS SNI в карточку сервера: {exc}")
        return False
    return True


def _save_pin_from_logs(
    server: Server,
    data: Any,
    sni: str,
    emit: Optional[Callable[[str, str], None]] = None,
) -> str:
    pin = pin_sha256_from_setup_logs(data)
    if not pin:
        return ""
    try:
        save_hysteria_tls_meta_to_server(server, pin=pin, sni=sni)
    except Exception as exc:
        if emit:
            emit(
                "ERROR",
                f"Отпечаток сертификата прочитан, но в карточку сервера не записался: {exc}",
            )
        return ""
    if emit:
        emit("INFO", "В карточку сервера записаны Hysteria TLS SNI и pinSHA256.")
    return pin


def _hysteria_setup_reached(logs_text: str) -> bool:
    """Панель дошла до сервера, даже если служба потом не поднялась."""
    text = (logs_text or "").lower()
    return any(
        marker in text
        for marker in (
            "hysteria",
            "key.pem",
            "cert.pem",
            "systemd",
            "setup completed",
            "ssh connected",
        )
    )


def hysteria_restart_looks_failed(logs_text: str) -> bool:
    """
    systemctl status после restart. Старый FATAL в journalctl не считается,
    если текущее состояние — active (running).
    """
    text = logs_text or ""
    if "Active: active (running)" in text or "server up and running" in text:
        return False
    if "Active:" in text or "permission denied" in text.lower():
        return True
    return False


def _pull_pin_via_panel_setup(
    api: CelerityAPI,
    node_id: str,
    server: Server,
    sni: str,
    emit: Callable[[str, str], None],
) -> Tuple[str, bool]:
    """
    Короткий setup: права на key.pem, pinSHA256, затем панель перезапускает hysteria-server.
    Returns (pin, restart_failed).
    """
    ok_put, err_put = api.update_node(node_id, {"initScript": HYSTERIA_PIN_INIT_SCRIPT})
    if not ok_put:
        emit(
            "WARNING",
            f"Не удалось отправить на сервер команду снятия отпечатка сертификата: {err_put!r}",
        )
        return "", False
    emit("INFO", "Выставляю права на ключ и перезапускаю службу Hysteria.")
    ok_pin, data_pin = api.setup_node(
        node_id,
        data={
            "installHysteria": False,
            "setupPortHopping": False,
            "restartService": True,
        },
        request_timeout=180,
    )
    logs_text = flatten_setup_logs(data_pin)
    api.update_node(node_id, {"initScript": ""})
    pin = _save_pin_from_logs(server, data_pin, sni, emit)
    if not ok_pin and "Active: active (running)" not in logs_text and "server up and running" not in logs_text:
        emit(
            "WARNING",
            "Повторный запуск Hysteria панель не засчитала успешным. "
            "SNI и отпечаток из журнала всё равно записываю в карточку сервера.",
        )
        return pin, True
    if "HYSTERIA_KEY_NOT_READABLE" in logs_text or hysteria_restart_looks_failed(logs_text):
        emit(
            "ERROR",
            "Hysteria не может прочитать ключ сертификата, служба после перезапуска не поднялась.",
        )
        return pin, True
    if "HYSTERIA_KEY_READABLE" in logs_text or "active (running)" in logs_text:
        emit("INFO", "Служба Hysteria запущена, ключ сертификата ей доступен.")
    return pin, False



def _node_document(payload: Any) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("node"), dict):
        return payload["node"]
    return payload if isinstance(payload, dict) else {}


def _node_obfs(payload: Any) -> Tuple[str, str]:
    obfs = _node_document(payload).get("obfs")
    if not isinstance(obfs, dict):
        return "", ""
    return str(obfs.get("type") or "").strip().lower(), str(obfs.get("password") or "").strip()


def _node_obfs_password(payload: Any) -> str:
    kind, password = _node_obfs(payload)
    if kind != "salamander" or not password:
        return ""
    return password


def generated_config_has_salamander(body: Any) -> bool:
    """В собранном конфиге есть блок обфускации Salamander, не просто слово в комментарии."""
    if isinstance(body, dict):
        text = json.dumps(body, ensure_ascii=False)
    else:
        text = str(body or "")
    if _OBFS_SALAMANDER_LINE.search(text):
        return True
    lowered = text.lower().replace("\\n", "\n").replace("\\r", "")
    if '"type": "salamander"' in lowered or "'type': 'salamander'" in lowered:
        return True
    return _OBFS_SALAMANDER_LINE.search(lowered) is not None


def _push_node_config(api: CelerityAPI, node_id: str, emit: Callable[[str, str], None]) -> Tuple[bool, str]:
    last = "Панель не ответила на отправку конфига"
    for attempt in range(1, 4):
        ok_cfg, err_cfg = api.update_node_config(node_id)
        if ok_cfg:
            return True, ""
        last = f"Не удалось отправить конфиг на сервер: {err_cfg!r}"[:1500]
        emit("DEBUG", f"{last}. Попытка {attempt} из 3.")
        if attempt < 3:
            time.sleep(5)
    return False, last


def save_hysteria_salamander(
    api: CelerityAPI,
    node_id: str,
    emit: Callable[[str, str], None],
    password: str = "",
) -> Tuple[bool, str]:
    """
    Записывает obfs salamander в карточку ноды. На сервер конфиг не отправляет.

    Уже заданный пароль не меняется и в лог не попадает.
    API это поле молча выбрасывает, поэтому при пустом ответе GET идёт форма панели.
    Запись нужна до установки: иначе Hysteria собирает конфиг без обфускации,
    а поздний пуш панель часто затирает.
    """
    ok, node = api.get_node(node_id)
    if not ok:
        detail = (
            "Не удалось прочитать ноду в панели перед записью обфускации. "
            "Проверьте, что панель Celerity открывается и у API-ключа есть право менять ноды. "
            "Затем запустите инициализацию снова."
        )
        emit("ERROR", detail)
        return False, detail
    if _node_obfs_password(node):
        emit("INFO", "Обфускация Salamander уже включена. Пароль не меняю и в лог не пишу.")
        return True, "obfs salamander уже задан"

    password = password or new_salamander_password()
    ok_put, _err = api.update_node(
        node_id,
        {"obfs": {"type": "salamander", "password": password}},
    )
    if not ok_put:
        detail = (
            "Панель отклонила запись обфускации. "
            "Откройте ноду в Celerity, включите Salamander и нажмите «Настроить сервер». "
            "Потом снимите галку Celerity у этого сервера в админке и запустите инициализацию снова."
        )
        emit("ERROR", detail)
        return False, detail
    ok_check, node_after = api.get_node(node_id)
    if ok_check and _node_obfs_password(node_after):
        emit("INFO", "Обфускация Salamander записана в карточку ноды.")
        return True, "obfs salamander записан"

    emit(
        "INFO",
        "Обычный запрос к панели обфускацию не сохраняет: этого поля нет в списке разрешённых. "
        "Записываю её через форму панели, тем же способом, что и кнопка сохранения ноды.",
    )
    ok_form, form_detail = save_node_obfs_via_panel(node_id, node, password)
    if not ok_form:
        emit("ERROR", form_detail)
        return False, form_detail
    ok_check, node_after = api.get_node(node_id)
    if not (ok_check and _node_obfs_password(node_after)):
        detail = (
            "Форма панели ответила без ошибки, но при повторном чтении обфускации нет. "
            "Откройте ноду в Celerity, включите Salamander, сохраните карточку и нажмите «Настроить сервер». "
            "Затем снимите галку Celerity у этого сервера и запустите инициализацию снова."
        )
        emit("ERROR", detail)
        return False, detail
    emit("INFO", "Обфускация Salamander записана в карточку ноды через форму панели.")
    return True, "obfs salamander записан"


def confirm_hysteria_salamander_pushed(
    api: CelerityAPI,
    node_id: str,
    emit: Callable[[str, str], None],
) -> Tuple[bool, str]:
    """Отправляет конфиг на сервер и проверяет, что панель собрала его уже с Salamander."""
    ok_cfg, err_cfg = _push_node_config(api, node_id, emit)
    if not ok_cfg:
        detail = (
            f"{err_cfg}. Карточка ноды с обфускацией уже сохранена, на сервер конфиг не ушёл. "
            "Подождите минуту и запустите инициализацию снова: сервер мог быть занят установкой. "
            "Если повтор не поможет, откройте ноду в Celerity и нажмите «Настроить сервер»."
        )
        emit("ERROR", detail)
        return False, detail

    read_config = getattr(api, "get_node_config", None)
    if not callable(read_config):
        return _confirm_salamander_on_node(api, node_id, emit)
    ok_text, body = read_config(node_id)
    if ok_text and generated_config_has_salamander(body):
        emit("INFO", "В конфиге, который панель собрала для сервера, есть обфускация Salamander.")
        return True, "конфиг содержит salamander"
    if ok_text:
        detail = (
            "Панель собрала конфиг без обфускации Salamander. "
            "В карточке ноды она не включена так, как её читает панель, поэтому на сервер ушёл бы обычный конфиг. "
            "Откройте ноду в Celerity, выберите Salamander, сохраните и нажмите «Настроить сервер». "
            "Затем снимите галку Celerity у этого сервера в админке и запустите инициализацию снова."
        )
        emit("ERROR", detail)
        return False, detail
    emit(
        "INFO",
        "Текст конфига отдельно прочитать не удалось. Проверяю карточку ноды: "
        "без Salamander в ней сервер в выдачу не попадёт.",
    )
    return _confirm_salamander_on_node(api, node_id, emit)


def _confirm_salamander_on_node(
    api: CelerityAPI,
    node_id: str,
    emit: Callable[[str, str], None],
) -> Tuple[bool, str]:
    ok_check, node_after = api.get_node(node_id)
    if ok_check and _node_obfs_password(node_after):
        emit("INFO", "Панель подтвердила обфускацию Salamander в карточке ноды.")
        return True, "obfs salamander подтверждён"
    kind, _password = _node_obfs(node_after if ok_check else {})
    detail = (
        "Панель не сохранила обфускацию"
        + (f": в ответе тип «{kind or 'пусто'}»." if ok_check else ".")
        + " Откройте ноду в Celerity, включите Salamander и нажмите «Настроить сервер»."
    )
    emit("ERROR", detail)
    return False, detail


def ensure_hysteria_salamander(
    api: CelerityAPI,
    node_id: str,
    emit: Callable[[str, str], None],
) -> Tuple[bool, str]:
    """Записывает salamander и сразу отправляет конфиг. Для установки ноды используйте два шага отдельно."""
    ok, detail = save_hysteria_salamander(api, node_id, emit)
    if not ok:
        return False, detail
    return confirm_hysteria_salamander_pushed(api, node_id, emit)


def bootstrap_celerity_for_server(
    server: Server,
    *,
    api: Optional[CelerityAPI] = None,
    node_type: str = "hysteria",
    setup_timeout: int = 300,
    log_fn: Optional[Callable[[str, str], None]] = None,
    init_script: Optional[str] = None,
    setup_body: Optional[dict] = None,
    salamander: bool = False,
) -> Tuple[bool, str]:
    """
    provision + setup для одного Server. При успехе — is_c3celeryty_activated=True.

    salamander=True только для новой ноды с ролью Hysteria2. Обфускация пишется
    в карточку до установки, галка ставится после проверки собранного конфига.
    Старым серверам флаг не передаётся.

    log_fn(level, message) — опционально (например для Logging в БД).
    """
    def _emit(level: str, msg: str) -> None:
        if log_fn:
            log_fn(level, msg)

    ip = (server.ip_address or "").strip()
    if not ip:
        detail = (
            "У сервера не указан IP. Впишите адрес в карточке сервера и запустите инициализацию снова."
            if salamander
            else "Пустой ip_address"
        )
        _emit("ERROR", detail)
        return False, detail

    if django_ssh_looks_weak(server):
        if salamander:
            detail = (
                "Пароль SSH у этого сервера пустой или стоит заглушка. "
                "Панель заходит на сервер по этому паролю, без него Hysteria не установится. "
                "Впишите настоящий пароль root в карточке сервера и запустите инициализацию снова."
            )
            _emit("ERROR", detail)
            return False, detail
        _emit("WARNING", "пустой или заглушечный SSH password")
        return False, "Пустой или заглушечный SSH password"

    api = api or CelerityAPI()

    try:
        group_id = _celerity_group_id(api)
    except RuntimeError as e:
        detail = str(e)
        if salamander:
            detail = (
                f"{detail} "
                "Проверьте ключ API панели и имя группы серверов в настройках, затем запустите инициализацию снова."
            )
        _emit("ERROR", detail)
        return False, detail

    if salamander:
        _emit("INFO", f"Шаг 1. Ищу в панели сервер {ip}.")
    ok_find, node_id = api.find_node_id_by_ip(ip, node_type)
    obfs_password = ""
    if salamander and not ok_find:
        obfs_password = new_salamander_password()
    if not ok_find:
        if salamander:
            _emit(
                "INFO",
                "В панели такой ноды нет. Создаю её одним запросом: карточка, "
                "обфускация Salamander и пароль из 16 символов. Пароль в лог не пишу. "
                "Прыжки портов не включаю, нода будет только на 443.",
            )
        else:
            _emit("DEBUG", "POST /nodes (создание ноды)")
        ok_c, nid, err_c = create_celerity_node_or_find(
            api, server, group_id, node_type, ip, obfs_password=obfs_password
        )
        if not ok_c:
            detail = f"create_node: {err_c!r}"
            if salamander:
                detail = (
                    f"Не удалось создать ноду в панели: {err_c!r}. "
                    "Проверьте, что панель отвечает и у API-ключа есть право создавать ноды. "
                    "Затем запустите инициализацию снова."
                )
            _emit("ERROR", detail)
            return False, detail
        node_id = nid
        if salamander:
            _emit("INFO", "Карточка ноды создана.")
    elif salamander:
        _emit("INFO", "Нода с этим адресом уже есть. Буду настраивать её, новую не создаю.")
    else:
        _emit("DEBUG", f"нода уже в панели node_id={node_id!r}")

    if salamander:
        _emit(
            "INFO",
            "Шаг 2. Включаю обфускацию Salamander до установки Hysteria. "
            "Пароль в лог не пишу. Если он уже был задан, оставляю его как есть.",
        )
        ok_obfs, obfs_detail = save_hysteria_salamander(
            api, node_id, _emit, password=obfs_password
        )
        if not ok_obfs:
            return False, obfs_detail

    sni = resolve_celerity_node_sni()
    if salamander:
        if remember_hysteria_sni(server, sni, _emit):
            _emit("INFO", f"В карточку сервера записан Hysteria TLS SNI: {sni}.")
    node_update: dict = {"sni": sni}
    if salamander:
        # Пустой диапазон панель подменяет на 20000-50000 и снова зовёт iptables.
        # «443» без дефиса скрипт прыжков пропускает.
        node_update["portRange"] = "443"
        node_update["subscriptionVariants"] = "tls"
    if init_script:
        node_update["initScript"] = init_script
        if salamander:
            _emit("INFO", "К установке приложен скрипт файрвола: панель выполнит его на сервере.")
        else:
            _emit("DEBUG", "initScript будет выполнен при setup")
    ok_sni, err_sni = api.update_node(node_id, node_update)
    if not ok_sni:
        detail = f"PUT sni={sni}: {err_sni!r}"
        if salamander:
            detail = (
                f"Не удалось записать адрес маскировки и скрипт установки: {err_sni!r}. "
                "Обфускация в карточке уже сохранена. Проверьте, что панель доступна, и запустите инициализацию снова."
            )
        _emit("ERROR", detail)
        return False, detail
    if not salamander:
        _emit("DEBUG", f"Hysteria TLS SNI={sni}")

    if salamander:
        _emit(
            "INFO",
            "Шаг 3. Ставлю Hysteria на сервер по SSH. Обычно это занимает несколько минут, "
            "страницу админки можно не обновлять.",
        )
    else:
        _emit("DEBUG", f"POST setup node_id={node_id!r} (timeout {setup_timeout}s)")
    ok_setup, data = api.setup_node(
        node_id,
        data=setup_body,
        request_timeout=setup_timeout,
    )
    logs_text = flatten_setup_logs(data)
    marzban_up = "MARZBAN_NODE_UP" in logs_text
    service_is_up = "Active: active (running)" in logs_text or "server up and running" in logs_text
    key_denied = (
        salamander
        and not service_is_up
        and "key.pem" in logs_text
        and "permission denied" in logs_text.lower()
    )
    if not ok_setup and not (salamander and (_hysteria_setup_reached(logs_text) or key_denied)):
        failed = f"setup_node: {data!r}"
        if marzban_up:
            failed = "MARZBAN_NODE_UP " + failed
        if salamander:
            failed = (
                "Установка Hysteria не завершилась. "
                "Чаще всего панель не смогла зайти на сервер по SSH или сервер ещё занят прошлой установкой. "
                "Проверьте пароль SSH и что порт 22 открыт. "
                "Если в панели у ноды написано, что она занята, подождите пару минут и запустите инициализацию снова. "
                f"Журнал панели: {failed[:800]}"
            )
        _emit("ERROR", failed[:1500])
        return False, failed
    if salamander and key_denied:
        _emit(
            "INFO",
            "Hysteria установлен, но служба сразу упала: она запущена от пользователя hysteria "
            "и не может прочитать ключ. Это не обрыв установки. "
            "Дальше перевожу службу на root и запускаю её снова.",
        )

    pin = _save_pin_from_logs(server, data, sni, _emit)
    if salamander:
        _emit(
            "INFO",
            "Шаг 4. Служба Hysteria переводится на root, ключу открывается чтение, "
            "снимается отпечаток сертификата и он записывается в карточку сервера вместе с SNI.",
        )
    fixed_pin, restart_failed = _pull_pin_via_panel_setup(api, node_id, server, sni, _emit)
    if fixed_pin:
        pin = fixed_pin
    if pin and not salamander:
        _emit("INFO", f"hysteria TLS meta: pin={pin[:8]}… sni={sni}")
    if pin and salamander:
        _emit("INFO", "Отпечаток сертификата сохранён. Клиент сможет проверить этот сервер.")
    if restart_failed:
        failed = "hysteria-server не online: нет прав на /etc/hysteria/key.pem"
        if marzban_up:
            failed = "MARZBAN_NODE_UP " + failed
        if salamander:
            failed = (
                "Hysteria установлен. SNI уже в карточке сервера, отпечаток тоже, если сертификат удалось прочитать. "
                "Служба при этом не поднялась: ключ /etc/hysteria/key.pem ей не доступен. "
                "На сервере должен появиться файл /etc/systemd/system/hysteria-server.service.d/zz-root.conf "
                "с User=root и Group=root. Выполните systemctl daemon-reload и systemctl restart hysteria-server. "
                "Если служба стала active, снимите галку Celerity и запустите инициализацию снова: "
                "обфускация и отпечаток допишутся в карточку."
            )
            _emit("ERROR", failed)
        return False, failed
    if not pin:
        synced = try_sync_hysteria_tls_meta_after_setup(
            server,
            log_fn=_emit,
            sni_override=sni,
            attempts=1 if init_script else 4,
        )
        if not synced:
            failed = "setup прошёл, но pinSHA256 не снят с /etc/hysteria/cert.pem"
            if marzban_up:
                failed = "MARZBAN_NODE_UP " + failed
            if salamander:
                failed += (
                    ". Установка дошла до конца, но отпечаток сертификата прочитать не удалось, "
                    "без него клиент не проверит сервер. "
                    "Откройте ноду в Celerity и нажмите «Настроить сервер». "
                    "Если в журнале снова нет отпечатка, проверьте, что Hysteria установлен "
                    "и на сервере есть файл /etc/hysteria/cert.pem. "
                    "Затем снимите галку Celerity и запустите инициализацию снова."
                )
                _emit("ERROR", failed[:1500])
            return False, failed

    if salamander:
        _emit(
            "INFO",
            "Шаг 5. Отправляю конфиг на сервер и проверяю, что в нём есть обфускация Salamander.",
        )
        ok_pushed, pushed_detail = confirm_hysteria_salamander_pushed(api, node_id, _emit)
        if not ok_pushed:
            return False, pushed_detail

    mark_server_c3_activated(server)
    detail = "MARZBAN_NODE_UP " if marzban_up else ""
    if isinstance(data, dict) and data.get("logs"):
        detail += json.dumps(data, ensure_ascii=False, default=str)[:1500]
    if salamander:
        done = (
            "Готово. Обфускация Salamander включена, сервер отмечен как настроенный и его можно выдавать клиентам."
        )
        _emit("INFO", done)
        return True, (detail + " " + done).strip()
    _emit("INFO", "setup OK, pinSHA256 сохранён, is_c3celeryty_activated=True")
    return True, detail or "OK"


def run_setup_init_script(
    server: Server,
    init_script: str,
    *,
    api: Optional[CelerityAPI] = None,
    setup_body: Optional[dict] = None,
    setup_timeout: int = 900,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Tuple[bool, str, str]:
    """
    Прогнать initScript через SSH панели Celerity, не помечая сервер как Hysteria.

    Returns:
        (setup_ok, detail, node_id). node_id пустой, если нода не создана.
    """
    def _emit(level: str, msg: str) -> None:
        if log_fn:
            log_fn(level, msg)

    ip = (server.ip_address or "").strip()
    if not ip:
        _emit("ERROR", "пустой ip_address")
        return False, "Пустой ip_address", ""
    if django_ssh_looks_weak(server):
        _emit("WARNING", "пустой или заглушечный SSH password")
        return False, "Пустой или заглушечный SSH password", ""

    api = api or CelerityAPI()
    try:
        group_id = _celerity_group_id(api)
    except RuntimeError as exc:
        _emit("ERROR", str(exc))
        return False, str(exc), ""

    ok_find, found = api.find_node_id_by_ip(ip, "hysteria")
    if ok_find:
        node_id = found
        _emit("DEBUG", f"временная нода уже в панели node_id={node_id!r}")
    else:
        _emit("DEBUG", "POST /nodes (временная нода для SSH)")
        ok_c, node_id, err_c = create_celerity_node_or_find(
            api, server, group_id, "hysteria", ip
        )
        if not ok_c:
            _emit("ERROR", f"create_node: {err_c!r}")
            return False, f"create_node: {err_c!r}", ""

    node_update = {"sni": resolve_celerity_node_sni(), "initScript": init_script}
    ok_put, err_put = api.update_node(node_id, node_update)
    if not ok_put:
        _emit("ERROR", f"PUT initScript: {err_put!r}")
        return False, f"PUT initScript: {err_put!r}", node_id

    body = setup_body if setup_body is not None else {
        "installHysteria": False,
        "setupPortHopping": False,
        "restartService": False,
    }
    _emit("DEBUG", f"POST setup node_id={node_id!r} (timeout {setup_timeout}s)")
    ok_setup, data = api.setup_node(node_id, data=body, request_timeout=setup_timeout)
    logs_text = flatten_setup_logs(data)
    if not ok_setup:
        detail = f"setup_node: {data!r}"
        if "MARZBAN_NODE_UP" in logs_text:
            detail = "MARZBAN_NODE_UP " + detail
        _emit("ERROR", detail[:1500])
        return False, detail, node_id

    detail = logs_text or "OK"
    if "MARZBAN_NODE_UP" not in detail and "MARZBAN_NODE_UP" in str(data):
        detail = "MARZBAN_NODE_UP " + detail
    _emit("INFO", "initScript выполнен")
    return True, detail, node_id


MARZBAN_NODE_CHECK_SCRIPT = r"""#!/bin/bash
set +e
running="$(docker inspect -f '{{.State.Running}}' marzban-node 2>/dev/null || echo false)"
if [ "$running" = "true" ]; then
  echo MARZBAN_NODE_UP
  exit 0
fi
echo MARZBAN_NODE_NOT_RUNNING
exit 1
"""


def setup_response_pending(detail: str) -> bool:
    """Ответ setup оборвался или нода ещё занята предыдущей установкой."""
    text = (detail or "").lower()
    return any(
        needle in text
        for needle in (
            "node is busy",
            "timed out",
            "time-out",
            "connection aborted",
            "connection reset",
            "502",
            "503",
            "504",
            "gateway",
        )
    )


def wait_for_marzban_node(
    server: Server,
    *,
    api: CelerityAPI,
    attempts: int = 20,
    pause_seconds: int = 20,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Tuple[bool, str, str]:
    """
    Короткий setup только проверяет контейнер.

    Долгий docker pull часто не укладывается в таймаут прокси перед панелью.
    Установка на сервере при этом продолжается, и следующая проверка её видит.
    """
    last_detail = ""
    last_id = ""
    for attempt in range(1, attempts + 1):
        if log_fn:
            log_fn("DEBUG", f"проверка marzban-node, попытка {attempt}")
        _ok, detail, node_id = run_setup_init_script(
            server,
            MARZBAN_NODE_CHECK_SCRIPT,
            api=api,
            setup_body={
                "installHysteria": False,
                "setupPortHopping": False,
                "restartService": False,
            },
            setup_timeout=180,
            log_fn=None,
        )
        last_detail = detail or ""
        if node_id:
            last_id = node_id
        if "MARZBAN_NODE_UP" in last_detail:
            return True, last_detail, last_id
        if not setup_response_pending(last_detail):
            return False, last_detail, last_id
        if attempt < attempts:
            time.sleep(pause_seconds)
    return False, last_detail, last_id
