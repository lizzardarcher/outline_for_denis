import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, View
from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, login
from django.urls import reverse

from bot.models import Prices, TelegramUser

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    template_name = 'home/index.html'

    def get_context_data(self, **kwargs):
        super().get_context_data(**kwargs)


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


class LoginView(TemplateView):
    template_name = 'account/login.html'


class ContactsView(TemplateView):
    template_name = 'home/contacts.html'


class AdvantagesView(TemplateView):
    template_name = 'home/advantages.html'


class SiteMapView(TemplateView):
    template_name = 'home/sitemap.html'


class ProfileView(SuccessMessageMixin, TemplateView):
    template_name = 'account/index.html'


# @require_POST
def telegram_login(request):
    data = request.GET.dict()
    try:
        user = authenticate(request, data=data)
    except Exception as e:
        messages.error(request, f'Could not login : {data}')
    if user:
        login(request, user)
        messages.success(request, "You are now logged in successfully.")
        return redirect(reverse('profile '))
    else:
        messages.error(request, f"Authentication failed. Data received: {data}")
        messages.error(request, f"Authentication from: {authenticate(request, data=data).__dir__()}")
        messages.error(request, f"User: {user}")
        return redirect(reverse('home'))

