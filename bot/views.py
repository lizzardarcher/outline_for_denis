from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse
from django.views.generic import TemplateView, DetailView, View
from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, login
from django.views.decorators.http import require_POST
from django.urls import reverse
from django_telegram_login.authentication import verify_telegram_authentication
from django_telegram_login.errors import TelegramDataIsOutdatedError, NotTelegramDataError
from django_telegram_login.widgets.constants import SMALL
from django_telegram_login.widgets.generator import create_callback_login_widget

from bot.models import Prices, TelegramUser

bot_name = settings.TELEGRAM_BOT_NAME
bot_token = settings.TELEGRAM_BOT_TOKEN
redirect_url = settings.TELEGRAM_LOGIN_REDIRECT_URL


class HomeView(TemplateView):
    template_name = 'home/index.html'

    def get_context_data(self, **kwargs):
        super().get_context_data(**kwargs)
        messages.info(self.request, 'test info:')


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


def telegram_login(request):
    messages.success(request, f'{request.POST}')
    data = request.POST.dict()
    user = authenticate(request, data=data)
    if user:
        login(request, user)
        messages.success(request, f'{request.POST}')
        return redirect(reverse('profile'))
    else:
        messages.success(request, f'{request.POST}')
        return redirect(reverse('profile'))
