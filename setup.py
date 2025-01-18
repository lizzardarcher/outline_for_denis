import subprocess
import os
import traceback


def run_command(command):
    """Runs a shell command and prints output."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    print(f"Command: {' '.join(command)}")
    if stdout:
        print(f"Stdout: {stdout.decode()}")
    if stderr:
        print(f"Stderr: {stderr.decode()}")
    return process.returncode


def install_dependencies(project_name):
    """Installs necessary dependencies."""
    os.system("sudo apt update")
    os.system("sudo apt -y install python3.8-venv python3-pip nginx gunicorn python3-dev")
    os.system(f"python3 -m venv /opt/{project_name}/venv")
    os.system(f"source /opt/{project_name}/venv/bin/activate")
    os.system("pip3 install -r requirements.txt")



def configure_nginx(project_name, server_name):
    """Configures Nginx without SSL."""
    nginx_config = f"""
server {{
  listen 80;
  listen [::]:80;
  server_name {server_name};
  root /opt/outline_for_denis;

  location / {{
    include proxy_params;
    proxy_pass http://unix:/run/gunicorn.sock;
    proxy_set_header X-Real-IP $remote_addr;
  }}
        location /static/ {{
        alias /opt/{project_name}/static/;
    }}

    location /media/ {{
        alias /opt/{project_name}/static/media/;
    }}
}}
"""
    with open(f"/etc/nginx/sites-available/{project_name}", "w") as f:
        f.write(nginx_config)
    run_command(["ln", "-s", f"/etc/nginx/sites-available/{project_name}", f"/etc/nginx/sites-enabled/{project_name}"])
    run_command(["nginx", "-t"])
    run_command(["systemctl", "restart", "nginx"])


def create_gunicorn_service(project_name, user):
    """Создает сервис systemd для Gunicorn."""
    gunicorn_cmd = f"/opt/{project_name}/venv/bin/gunicorn -c gunicorn-cfg.py {project_name}.wsgi:application"  # Предполагает наличие wsgi файла
    service_file = f"""
[Unit]
Description=Gunicorn service for {project_name}
Requires={project_name}-gunicorn.socket
After=network.target

[Service]
Type=notify
NotifyAccess=main
User={user}
RuntimeDirectory=gunicorn
WorkingDirectory=/opt/{project_name}
Environment="PYTHONPATH=/opt/{project_name}"
ExecStart={gunicorn_cmd}
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    with open(f"/etc/systemd/system/{project_name}-gunicorn.service", "w") as f:
        f.write(service_file)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", f"{project_name}-gunicorn.service"])
    run_command(["systemctl", "start", f"{project_name}-gunicorn.service"])


def create_gunicorn_socket(project_name):
    """Создает сокет systemd для Gunicorn."""
    socket_file = f"""
[Unit]
Description=gunicorn socket for {project_name}

[Socket]
ListenStream=/run/gunicorn.sock
SocketUser=www-data
SocketGroup=www-data
SocketMode=0660

[Install]
WantedBy=sockets.target
"""
    with open(f"/etc/systemd/system/{project_name}-gunicorn.socket", "w") as f:
        f.write(socket_file)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", f"{project_name}-gunicorn.socket"])
    run_command(["systemctl", "start", f"{project_name}-gunicorn.socket"])


def create_vpn_bot_service(project_name):
    """Создает vpn bot systemd."""
    service_file = f"""
[Unit]
Description=Telegram bot {project_name}
After=syslog.target
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/{project_name}
Environment="PYTHONPATH=/opt/{project_name}"
ExecStart=/opt/{project_name}/venv/bin/python3 /opt/{project_name}/bot/main/tgbot.py
RestartSec=10
Restart=always

[Install]
WantedBy=multi-user.target
"""
    with open(f"/etc/systemd/system/{project_name}-vpnbot.service", "w") as f:
        f.write(service_file)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", f"{project_name}-vpnbot.service"])
    run_command(["systemctl", "start", f"{project_name}-vpnbot.service"])


def main():
    project_name = "outline_for_denis"  # Замените на имя вашего проекта
    server_name = "178.208.92.176"  # Замените на ваше доменное имя
    user = "root"  # Замените на имя пользователя, от имени которого будет запускаться Gunicorn

    if not os.path.exists("gunicorn-cfg.py"):
        print("Файл gunicorn-cfg.py не найден!")
        exit(1)
    if not os.path.exists("requirements.txt"):
        print("Файл requirements.txt не найден!")
        exit(1)

    install_dependencies(project_name)
    configure_nginx(project_name, server_name)
    create_gunicorn_service(project_name, user)
    create_gunicorn_socket(project_name)
    create_vpn_bot_service(project_name)

    print("Установка завершена!")


if __name__ == "__main__":
    main()
