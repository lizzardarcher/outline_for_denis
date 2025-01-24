
from django.urls import path, re_path
from django.views.decorators.csrf import csrf_exempt
from django.views.static import serve
from django.template.defaulttags import url
from django.conf import settings
from django.conf.urls.static import static

from bot import views


urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('price/', views.PriceView.as_view(), name='price'),
    path('contacts/', views.ContactsView.as_view(), name='contacts'),
    path('why/', views.WhyView.as_view(), name='why'),
    path('service/', views.ServiceView.as_view(), name='service'),
    path('oferta/', views.OfertaView.as_view(), name='oferta'),
    path('policy/', views.PolicyView.as_view(), name='policy'),
    path('advantages/', views.AdvantagesView.as_view(), name='advantages'),
    path('site_map/', views.SiteMapView.as_view(), name='site_map'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('telegram-login/', views.telegram_login, name='telegram_login'),
]