import paramiko

host = '185.119.58.72'
user = 'root'
secret = 'p?sV-JN?8yq_tR'
port = 22

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, username=user, password=secret, port=port)
stdin, stdout, stderr = client.exec_command('cat configfile.txt')
data = stdout.read() + stderr.read()
open('configfile.txt', 'w').write(data.__str__())
client.close()
