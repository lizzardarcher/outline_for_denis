import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_for_denis.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

