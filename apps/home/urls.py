from django.urls import path

from apps.home import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('price/', views.PriceView.as_view(), name='price'),
    path('contacts/', views.ContactsView.as_view(), name='contacts'),
    path('oferta/', views.OfertaView.as_view(), name='oferta'),
    path('policy/', views.PolicyView.as_view(), name='policy'),
    path('advantages/', views.AdvantagesView.as_view(), name='advantages'),
    path('site_map/', views.SiteMapView.as_view(), name='site_map'),
    path('outline_links/', views.OutlineLinksView.as_view(), name='outline_links'),
    path('robots.txt', views.RobotsTXTView.as_view(content_type="text/plain"), name='robots.txt'),
    # path('sitemap.xml/', views.SitemapXMLView.as_view(content_type="text/plain"), name='sitemap'),

]