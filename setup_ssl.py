import subprocess
import os


def run_command(command):
    """Runs a shell command and prints output."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = process.communicate()
    print(f"Command: {' '.join(command)}")
    if stdout:
        print(f"Stdout: {stdout.decode()}")
    if stderr:
        print(f"Stderr: {stderr.decode()}")
    return process.returncode


def install_dependencies():
    """Installs necessary dependencies."""
    commands = [
        ["apt-get", "update", "-y"],
        ["apt-get", "install", "-y", "python3-pip", "nginx", "gunicorn", "certbot", "python3-dev"],
        ["pip3", "install", "-r", "requirements.txt"]  # предполагает наличие requirements.txt
    ]
    for command in commands:
        if run_command(command) != 0:
            print("Ошибка при установке зависимостей!")
            exit(1)


def configure_nginx(project_name, server_name):
    """Configures Nginx."""
    nginx_config = f"""
server {{
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name {server_name};
  index index.php index.html index.htm index.nginx-debian.html;
  return 301 https://{server_name}$request_uri;
}}

server {{
  listen 443 ssl;
  listen [::]:443 ssl;
  server_name {server_name};

  ssl_certificate /etc/letsencrypt/live/{server_name}/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/{server_name}/privkey.pem;

  location / {{
    include proxy_params;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }}
}}
"""
    with open("/etc/nginx/sites-available/{project_name}".format(project_name=project_name), "w") as f:
        f.write(nginx_config)
    run_command(["ln", "-s", f"/etc/nginx/sites-available/{project_name}", "/etc/nginx/sites-enabled/{project_name}"])
    run_command(["nginx", "-t"])
    run_command(["systemctl", "restart", "nginx"])


def obtain_ssl_certificate(server_name):
    """Obtains an SSL certificate using Certbot."""
    run_command(
        ["certbot", "certonly", "--webroot", "-w", "/var/www/html", "-n", "--agree-tos", "-m", "your_email@example.com",
         "-d", server_name])  # Замените your_email@example.com на ваш email


def create_gunicorn_service(project_name, user):
    """Создает сервис systemd для Gunicorn."""
    gunicorn_cmd = f"gunicorn -c gunicorn-cfg.py {project_name}.wsgi:application"  # Предполагает наличие wsgi файла
    service_file = f"""
[Unit]
Description=Gunicorn service for {project_name}
After=network.target

[Service]
User={user}
Group=www-data
WorkingDirectory=/var/www/{project_name} # Измените путь к вашему проекту
ExecStart={gunicorn_cmd}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    with open(f"/etc/systemd/system/{project_name}-gunicorn.service", "w") as f:
        f.write(service_file)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", f"{project_name}-gunicorn"])
    run_command(["systemctl", "start", f"{project_name}-gunicorn"])


def create_gunicorn_socket(project_name):
    """Создает сокет systemd для Gunicorn."""
    socket_file = f"""
[Unit]
Description=Gunicorn socket for {project_name}
After=network.target

[Socket]
ListenStream=127.0.0.1:8000
# Если нужен другой порт, измените его здесь

[Install]
WantedBy=sockets.target
"""
    with open(f"/etc/systemd/system/{project_name}-gunicorn.socket", "w") as f:
        f.write(socket_file)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", f"{project_name}-gunicorn.socket"])
    run_command(["systemctl", "start", f"{project_name}-gunicorn.socket"])


def main():
    project_name = "outline_for_denis"  # Замените на имя вашего проекта
    server_name = "178.208.92.176"  # Замените на ваше доменное имя
    user = 'root'

    if not os.path.exists("gunicorn-cfg.py"):
        print("Файл gunicorn-cfg.py не найден!")
        exit(1)

    if not os.path.exists("requirements.txt"):
        print("Файл requirements.txt не найден!")
        exit(1)

    install_dependencies()
    obtain_ssl_certificate(server_name)
    configure_nginx(project_name, server_name)
    create_gunicorn_service(project_name, user)
    create_gunicorn_socket(project_name)

    print("Установка завершена!")


if __name__ == "__main__":
    main()
