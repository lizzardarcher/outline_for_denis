from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render
from django.views.generic import TemplateView

from bot.models import VpnKey


class ProfileView(SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['vpn_key'] = VpnKey.objects.get(user=self.request.user.profile.telegram_user)
        except VpnKey.DoesNotExist:
            ...
        return context