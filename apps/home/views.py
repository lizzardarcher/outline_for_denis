import logging
from django.contrib.messages.views import SuccessMessageMixin
from django.views.generic import TemplateView

from bot.models import Prices, Server

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    template_name = 'home/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['prices'] = Prices.objects.get(pk=1)
        context['servers'] = Server.objects.filter(is_active=True).values_list('country__name_for_app', flat=True).distinct()
        return context

class AboutView(TemplateView):
    template_name = 'home/about.html'


class PriceView(TemplateView):
    template_name = 'home/price.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['prices'] = Prices.objects.get(pk=1)
        return context




class OfertaView(TemplateView):
    template_name = 'home/oferta.html'


class PolicyView(TemplateView):
    template_name = 'home/policy.html'


class LoginView(TemplateView):
    template_name = 'account/login.html'


class ContactsView(TemplateView):
    template_name = 'home/contacts.html'


class AdvantagesView(TemplateView):
    template_name = 'home/advantages.html'


class SiteMapView(TemplateView):
    template_name = 'home/sitemap.html'


class OutlineLinksView(TemplateView):
    template_name = 'home/outline_links.html'


class RobotsTXTView(TemplateView):
    template_name = 'robots.txt'


class SitemapXMLView(TemplateView):
    template_name = 'sitemap.xml'

