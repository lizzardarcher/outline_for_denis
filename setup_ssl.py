import subprocess
import os


def run_command(command, check=True):
    print(f"Запускаем команду в shell: {command}")
    try:
        subprocess.run(command, shell=True, check=check, executable='/bin/bash')
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        exit(1)


def configure_nginx(project_name, server_name):
    """Configures Nginx."""
    nginx_config = f"""
server {{
    listen 80;
    server_name {server_name};
    # return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {server_name};
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload";
    ssl_certificate /etc/letsencrypt/live/{server_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{server_name}/privkey.pem;

    include /etc/letsencrypt/options-ssl-nginx.conf;
    client_max_body_size 1G;
    
    location / {{
        proxy_pass http://unix:/run/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /static/ {{
        alias /opt/{project_name}/static/;
        add_header X-Content-Type-Options nosniff;
        add_header Referrer-Policy "strict-origin-when-cross-origin";
        add_header X-Frame-Options DENY;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload";
        add_header Content-Security-Policy "default-src 'self' *stackpath.bootstrapcdn.com *cdnjs.cloudflare.com *code.jquery.com *yookassa.ru *ajax.googleapis.com *fonts.googleapis.com";
        }}
}}

    """
    with open(f"/etc/nginx/sites-available/{project_name}", "w") as f:
        f.write(nginx_config)
    os.system(f"ln -s /etc/nginx/sites-available/{project_name} /etc/nginx/sites-enabled/{project_name}")
    os.system("nginx -t")
    os.system("systemctl restart nginx")

def create_ssl_certificate(server_name, email):
    print("Создаем бесплатный SSL-сертификат с Let's Encrypt...")
    os.system("sudo apt install -y certbot")
    os.system("sudo apt install -y python3-certbot-nginx")
    os.system(f"sudo certbot --nginx -d {server_name} -m {email} --non-interactive --agree-tos")


def main():
    project_name = "outline_for_denis"
    server_name = "domvpn.ru"
    email = "vodkinstorage@gmail.com"

    configure_nginx(project_name, server_name)
    # create_ssl_certificate(server_name, email)

    print("Установка завершена!")

if __name__ == "__main__":
    main()
