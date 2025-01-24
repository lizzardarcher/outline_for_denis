# # -*- encoding: utf-8 -*-
import os
from glob import glob

command = '/opt/outline_for_denis/venv/bin/gunicorn'
pythonpath = '/opt/outline_for_denis'
log_file = '/var/log/gunicorn/bot.log'
bind = '0.0.0.0'
workers = 1
timeout = 600
accesslog = '/var/log/gunicorn/bot.log'
errorlog = '/var/log/gunicorn/error.log'
loglevel = 'debug'
capture_output = True
enable_stdio_inheritance = True
reload = True
reload_extra_files = glob('/opt/outline_for_denis/templates/**/*.html', recursive=True) + glob('/opt/outline_for_denis/static/**/*.css', recursive=True)