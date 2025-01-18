with open('configfile.txt', 'r') as config_file:
    config = config_file.read()
    for line in config.split(' '):
        if 'interface' in line:
            raw = line.split('{')[1].split('}')[0].split(',')
            data = dict()
            data['apiUrl'] = raw[0].split('":"')[-1].replace("'", "").replace('"', '')
            data['certSha256'] = raw[1].split(':')[-1].replace("'", "").replace('"', '')


print(data, type(data))