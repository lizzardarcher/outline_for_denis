# # -*- encoding: utf-8 -*-

command = '/opt/outline_for_denis/venv/bin/gunicorn'
pythonpath = '/opt/outline_for_denis'
bind = '0.0.0.0'
workers = 1
timeout = 600
accesslog = '-'
loglevel = 'info'
capture_output = True
enable_stdio_inheritance = True
reload = True