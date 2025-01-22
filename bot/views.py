from django.shortcuts import render
from django.views.generic import TemplateView

from bot.models import Prices


class HomeView(TemplateView):
    template_name = 'home/index.html'


class AboutView(TemplateView):
    template_name = 'home/about.html'


class PriceView(TemplateView):
    template_name = 'home/price.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['prices'] = Prices.objects.get(pk=1)
        return context


class WhyView(TemplateView):
    template_name = 'home/why.html'


class ServiceView(TemplateView):
    template_name = 'home/service.html'


class OfertaView(TemplateView):
    template_name = 'home/oferta.html'


class PolicyView(TemplateView):
    template_name = 'home/policy.html'


class ContactsView(TemplateView):
    template_name = 'home/contacts.html'


class AdvantagesView(TemplateView):
    template_name = 'home/advantages.html'


class SiteMapView(TemplateView):
    template_name = 'home/sitemap.html'
