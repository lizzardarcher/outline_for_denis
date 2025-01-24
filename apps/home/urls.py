from django.urls import path

from apps.home import views

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
]