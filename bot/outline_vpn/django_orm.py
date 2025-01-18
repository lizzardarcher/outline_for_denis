import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_v2.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

