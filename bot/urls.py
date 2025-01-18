
from django.urls import path, re_path
from django.views.static import serve
from django.template.defaulttags import url
from django.conf import settings
from django.conf.urls.static import static

from bot import views


urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
]

# urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
