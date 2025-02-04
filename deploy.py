import os
import shutil

# --- Конфигурация ---
PROJECT_NAME = "outline"
GITHUB_REPO = "https://github.com/lizzardarcher/outline_for_denis.git"
PROJECT_DIR = f"/opt/{PROJECT_NAME}"
VENV_DIR = f"{PROJECT_DIR}/venv"
DJANGO_SETTINGS_MODULE = f"{PROJECT_DIR}/{PROJECT_NAME}.settings"
NGINX_CONFIG_FILE = f"/etc/nginx/sites-available/{PROJECT_NAME}"
NGINX_SYMLINK = f"/etc/nginx/sites-enabled/{PROJECT_NAME}"
DOMAIN_NAME = "dom-vpn.ru"
TELEGRAM_BOT_FILE = f"{PROJECT_DIR}/bot/main/tgbot.py"
SYSTEMD_DIR = "/etc/systemd/system"
USER = "root"
EMAIL = "vodkinstorage@gmail.com"

def install_dependencies():
    """Устанавливает необходимые зависимости."""
    print("--- Установка зависимостей ---")
    os.system("sudo apt update")
    os.system("sudo apt install -y ")
    os.system("sudo apt install -y python3 ")
    os.system("sudo apt install -y python3-pip ")
    os.system("sudo apt install -y python3-venv ")
    os.system("sudo apt install -y nginx ")
    os.system("sudo apt install -y certbot ")
    os.system("sudo apt install -y python3-certbot-nginx")
    os.system("sudo apt install -y git")
    os.system("sudo apt install -y python3.12-venv")

def clone_repo():
    """Клонирует репозиторий из GitHub."""
    print("--- Клонирование репозитория ---")
    if os.path.exists(PROJECT_DIR):
        print(f"Каталог {PROJECT_DIR} уже существует. Удаление...")
        shutil.rmtree(PROJECT_DIR)
    os.system(f"git clone {GITHUB_REPO} {PROJECT_DIR}")

def setup_virtualenv():
    """Создает и активирует виртуальное окружение."""
    print("--- Настройка виртуального окружения ---")
    os.system(f"python3 -m venv {VENV_DIR}")
    os.system(f"{VENV_DIR}/bin/pip install -r {PROJECT_DIR}/requirements.txt")

def configure_nginx():
    """Настраивает Nginx."""
    print("--- Настройка Nginx ---")
    nginx_config = f"""
server {{
    listen 80;
    server_name {DOMAIN_NAME};

    location = /favicon.ico {{ access_log off; log_not_found off; }}
    location /static/ {{
        root {PROJECT_DIR};
    }}

    location / {{
        include proxy_params;
        proxy_pass http://unix:{PROJECT_DIR}/gunicorn.sock;
    }}
}}
"""

    f"""
    server {{
    listen 80;
    listen [::]:80;
    server_name {DOMAIN_NAME};
    # return 301 https://$host$request_uri;
}}

server {{
     listen 443 ssl;
     listen [::]:443 ssl;
     server_name {DOMAIN_NAME};
     proxy_connect_timeout       1200s;
     proxy_send_timeout          1200s;
     proxy_read_timeout          1200s;
     send_timeout                1200s;
     add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload";

     location / {{
        proxy_pass http://unix:/run/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
     location /static/ {{
        alias {PROJECT_DIR}/static/;
        add_header X-Content-Type-Options nosniff;
        add_header Referrer-Policy "strict-origin-when-cross-origin";
        add_header X-Frame-Options DENY;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload";
        add_header Content-Security-Policy "default-src 'self' *stackpath.bootstrapcdn.com *cdnjs.cloudflare.com *code.jquery.com *yookassa.ru *ajax.googleapis.com *fonts.googleapis.com";
        }}
 }}
 """


    with open(NGINX_CONFIG_FILE, "w") as f:
        f.write(nginx_config)

    # Удаляем стандартную ссылку default и создаем свою
    os.system("sudo rm -f /etc/nginx/sites-enabled/default")
    os.system(f"sudo ln -s {NGINX_CONFIG_FILE} {NGINX_SYMLINK}")

def install_ssl_certificate():
    """Устанавливает SSL сертификат с помощью Certbot."""
    print("--- Установка SSL сертификата ---")
    os.system(f"sudo certbot --nginx -d {DOMAIN_NAME} --non-interactive --agree-tos --email {EMAIL}") # Замените email

def create_systemd_services():
    """Создает systemd сервисы для Gunicorn и Telegram бота."""
    print("--- Создание systemd сервисов ---")

    # gunicorn.socket
    gunicorn_socket_content = f"""
[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock
SocketUser=www-data
SocketGroup=www-data
SocketMode=0660

[Install]
WantedBy=sockets.target
"""
    with open(f"{SYSTEMD_DIR}/gunicorn.socket", "w") as f:
        f.write(gunicorn_socket_content)

    # gunicorn.service
    gunicorn_service_content = f"""
[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
Type=notify
NotifyAccess=main
User={USER}
RuntimeDirectory=gunicorn
WorkingDirectory={PROJECT_DIR}
Environment="PYTHONPATH={PROJECT_DIR}"
ExecStart={PROJECT_DIR}/venv/bin/gunicorn -c gunicorn-cfg.py {PROJECT_NAME}.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""
    with open(f"{SYSTEMD_DIR}/gunicorn.service", "w") as f:
        f.write(gunicorn_service_content)


    # telegram_bot.service
    telegram_bot_service_content = f"""
[Unit]
Description=Telegram bot
After=syslog.target
After=network.target

[Service]
Type=simple
User={USER}
WorkingDirectory={PROJECT_DIR}
Environment="PYTHONPATH={PROJECT_DIR}"
ExecStart={PROJECT_DIR}/venv/bin/python3 {PROJECT_DIR}/bot/main/tgbot.py
RestartSec=10
Restart=always

[Install]
WantedBy=multi-user.target
"""

    with open(f"{SYSTEMD_DIR}/telegram_bot.service", "w") as f:
        f.write(telegram_bot_service_content)



def start_services():
    """Запускает systemd сервисы и перезагружает Nginx."""
    print("--- Запуск сервисов ---")
    os.system("sudo systemctl daemon-reload")
    os.system("sudo systemctl start gunicorn.socket")
    os.system("sudo systemctl enable gunicorn.socket")
    os.system("sudo systemctl start gunicorn.service")
    os.system("sudo systemctl enable gunicorn.service")
    os.system("sudo systemctl start telegram_bot.service")
    os.system("sudo systemctl enable telegram_bot.service")
    os.system("sudo systemctl restart nginx")

# --- Основной скрипт ---
if __name__ == "__main__":
    install_dependencies()
    clone_repo()
    setup_virtualenv()
    configure_nginx()
    install_ssl_certificate()
    create_systemd_services()
    start_services()

    print("Развертывание завершено!")