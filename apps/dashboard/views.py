from audioop import reverse

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.views.generic import TemplateView, CreateView, UpdateView

from bot.models import VpnKey, Server, TelegramUser, Country, Prices


class ProfileView(LoginRequiredMixin, SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['servers'] = Server.objects.filter(is_active=True).values_list('country__name_for_app',
                                                                               flat=True).distinct()
        try:
            context['vpn_key'] = VpnKey.objects.select_related('user').get(user=self.request.user.profile.telegram_user)
        except VpnKey.DoesNotExist:
            ...
        context['total_users'] = TelegramUser.objects.count()
        context['countries'] = Country.objects.filter(is_active=True)
        context['subscription'] = Prices.objects.get(id=1)
        return context


class CreateNewKeyView(LoginRequiredMixin, SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/create_key.html'

    def get_success_url(self):
        return reverse('profile')

    def get_success_message(self, cleaned_data):
        return 'New key has been created!'

class UpdateKeyView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    ...
