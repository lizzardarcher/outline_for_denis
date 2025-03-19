import os
import paramiko
import subprocess

cloud_init ="""#!/bin/bash

# Set variables (you can also pass these as arguments)
CERT="-----BEGIN CERTIFICATE-----\nMIIEnDCCAoQCAQAwDQYJKoZIhvcNAQENBQAwEzERMA8GA1UEAwwIR296YXJnYWgw\nIBcNMjUwMzE3MTAxOTQyWhgPMjEyNTAyMjExMDE5NDJaMBMxETAPBgNVBAMMCEdv\nemFyZ2FoMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEApUCVwqUWeX6R\nfX+8KmTYg3E1FaY/d+oBxWa7ABTK/RjD6jrYh5jtmopbeaITuzp7Z8aobSbrVx7c\nZNHAQISJdJhZPqL+qLySFVdIh7qfBmW7WI0JRG4UBPX+vh3rOydidLPGXMdyy534\nkvUvco63XK///vC+CHAfws2lxcPj70FX702WkKNNCHH9vGiDSr2qoHWSwSObwbF/\nMuIbxNtCfKsgblZ+FcmLf/3LCEzbFGAnx6+1o7KVPvHtg5I9qWhwar2ntB2JSJ7p\nkqyFDOEecXrXKBObUAjaeIWAE3QthUaLbFTuZGcv8Jdult2z+0AeGjYv6Qcn++C5\ncE/DjUYKTibsDHlDTMebm5cGTQQF8sEeXEAXQPucV18HWcvtmdl4WeXWmlO9osDs\nN1kvpt6ECC8/ihb5kLUrVKaoPkmUCSKqAaxfVrLHIr64So9ZgmvmZv1LcZDp7ji0\nS24PlG3ztfg6RnynteYey6+HOm5KJBtKL6ALsj87ZiYdVzca9WNVKXfzF0I1DbY4\nIDngKjvoeftjzGD64cNM1HvHUeR8uqhpiLeLHrEahPx7mXpVqcvx7+WSYrzbde4l\ni9yCrDRHzoQAi5kDi+hdiuItQIzbVh54AtVnmF8XLliu8vwEdSBJgJ2Jy9TBjVA7\n8ijRyNpT+8c67XqHBVA/9ZXpolSx3GcCAwEAATANBgkqhkiG9w0BAQ0FAAOCAgEA\nNdXGyIPmoxWwGXPF1b6jp8wxdf94fdydVDFea2sJIb4iXRD8GEl2aJAXG75xmn5c\nrHerGG7iEXWF2FImkze8+zYHI31HP6nhZvKqT08OUVxf/6+0zmEo/RUxngzyPI1F\nSRi+ao53VGwWoIdcd/KjDty1I2CXccB7xfh/jOJdmLPopPQZLXMq2FLJ/efE21IP\n4YwmCVNwUuuyRs8V3RiKlPlWrrdSuvdDjKlu3sEGuVzy9YE7mAg7eY7vlYpB3XiM\ncIi6R4a0pZd5sdKFFH5mdhp0xKrLqlO+5fjCOzVTVkDOZSeVaedNuTfcScJvVmUJ\nF/yrOvKzFJw+uYltNob7iPgt4H8uVidhsrxTS/WMLK/4gbMyYV/sTPqklPNLqzF2\nKV3GJDht6nqKbCkCnZUS0ZN6F0CwTUw3xvEli3KSVJ2fkh9yaNlrvkqv7AMTrB8b\n/Qxo0tNL1p0u8UKRfARXRpMCs9zE+PPm5NjnKg2Y9+lbf6ZPrmcTMESHVbL2cdAf\n/oP+3mTDkXaexLdIaqGhn95m88rqO38fNTc6odGIBGC1v93zrAEFqB+MLTryPSwK\n7eBBQvWaV4fMI88FLOv8TqVmRDZNI972CHU0tvFaLTZ21V3a1zKT/cKyOs44Y8ui\ncCWzgxcswewONXi6yhxefFx14Z2jx9eoa4kbwJvHteU=\n-----END CERTIFICATE-----\n"
DOCKER_COMPOSE_YML="services:
  marzban-node:
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host

    volumes:
      - /var/lib/marzban-node:/var/lib/marzban-node

    environment:
      SSL_CLIENT_CERT_FILE: \"/var/lib/marzban-node/ssl_client_cert.pem\"
      SERVICE_PROTOCOL: rest"

execute_command() {
  command="$1"
  description="$2"
  echo "Executing: $description"
  eval "$command"
  if [ $? -ne 0 ]; then
    echo "Error: $description failed. Exiting."
    exit 1
  fi
}

execute_command "sudo apt-get update -y" 
execute_command "sudo apt-get install -y socat curl git " 
execute_command "git clone https://github.com/Gozargah/Marzban-node" 
execute_command "mkdir -p /var/lib/marzban-node/" 
execute_command "echo \"$CERT\" > /var/lib/marzban-node/ssl_client_cert.pem"
execute_command "cd Marzban-node && echo \"$DOCKER_COMPOSE_YML\" > /Marzban-node/docker-compose.yml && docker-compose up -d"

echo "Script completed successfully."
"""





def execute_remote_script(hostname, username, password):
    try:
        # Создаем SSH клиент
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # Автоматически добавляем хост в known_hosts (не безопасно для production)

        # Подключаемся к удаленному серверу
        ssh_client.connect(hostname=hostname, username=username, password=password)

        # Формируем команду для выполнения скрипта
        command = cloud_init

        # Выполняем команду
        stdin, stdout, stderr = ssh_client.exec_command(command)

        # Читаем вывод и ошибки
        stdout_output = stdout.read().decode('utf-8')
        stderr_output = stderr.read().decode('utf-8')

        # Получаем код возврата
        return_code = stdout.channel.recv_exit_status()

        # Закрываем SSH соединение
        ssh_client.close()

        return stdout_output, stderr_output, return_code

    except paramiko.AuthenticationException:
        print("Ошибка аутентификации. Неверное имя пользователя или пароль.")
        return None
    except paramiko.SSHException as e:
        print(f"Ошибка SSH: {e}")
        return None
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        return None


"""
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@178.208.78.100:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20MC%20HOST%20NL1%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@45.87.247.252:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20kvmka%20RU1%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@45.15.156.52:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20kvmka%20de1%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@2.56.127.115:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20%F0%9F%87%B9%F0%9F%87%B7%20pq.hosting%20TR1%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@45.12.139.254:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9B%D1%8E%D0%BA%D1%81%D0%B5%D0%BC%D0%B1%D1%83%D1%80%D0%B3%20%F0%9F%87%B1%F0%9F%87%BA%20pq.hosting%20LU%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@91.132.132.120:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%90%D1%80%D0%BC%D0%B5%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A6%F0%9F%87%B2%20pq.hosting%20AM%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@185.142.33.24:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20kvmka%20de2%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@2.56.177.127:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20pq.hosting%20KZ3%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@178.208.78.182:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20MC%20HOST%20NL2%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@31.130.152.230:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20timeweb-cloud%20KZ2%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
vless://a37e7142-7ba6-4f95-adde-0fbe04cbbd41@103.106.3.58:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20pq.hosting%20KZ%20%28babyddbb125432%29%20%5BVLESS%20-%20tcp%5D
"""