# # -*- encoding: utf-8 -*-
import os
from glob import glob

command = '/opt/outline/venv/bin/gunicorn'
pythonpath = '/opt/outline'
bind = '0.0.0.0'
workers = 5
timeout = 600
loglevel = 'debug'
capture_output = True
enable_stdio_inheritance = True
reload = True
reload_extra_files = glob('/opt/outline/templates/**/*.html', recursive=True) + glob('/opt/outline/static/**/*.css', recursive=True)