from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render
from django.views.generic import TemplateView

from bot.main.timeweb.das import server
from bot.models import VpnKey, Server, TelegramUser


class ProfileView(SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['servers'] = Server.objects.filter(is_active=True).values_list('country__name_for_app', flat=True).distinct()
        try:
            context['vpn_key'] = VpnKey.objects.select_related('user').get(user=self.request.user.profile.telegram_user)
        except VpnKey.DoesNotExist:
            ...
        context['total_users'] = TelegramUser.objects.count()
        return context