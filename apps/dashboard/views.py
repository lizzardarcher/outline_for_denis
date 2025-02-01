from datetime import timedelta, datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView

from apps.dashboard.outline_vpn.outline_client import delete_user_keys, create_new_key
from bot.models import VpnKey, Server, TelegramUser, Country, Prices, UserProfile, ReferralSettings, TelegramReferral, \
    Transaction, Logging


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
        context['referral'] = ReferralSettings.objects.get(pk=1)
        context['inv_1_lvl'] = TelegramReferral.objects.filter(referrer=self.request.user.profile.telegram_user, level=1).__len__()
        context['inv_2_lvl'] = TelegramReferral.objects.filter(referrer=self.request.user.profile.telegram_user, level=2).__len__()
        context['inv_3_lvl'] = TelegramReferral.objects.filter(referrer=self.request.user.profile.telegram_user, level=3).__len__()
        context['inv_4_lvl'] = TelegramReferral.objects.filter(referrer=self.request.user.profile.telegram_user, level=4).__len__()
        context['inv_5_lvl'] = TelegramReferral.objects.filter(referrer=self.request.user.profile.telegram_user, level=5).__len__()
        context['transactions'] = Transaction.objects.filter(user=self.request.user.profile.telegram_user)
        return context


class CreateNewKeyView(LoginRequiredMixin, TemplateView):

    def get(self, request, *args, **kwargs):
        country_name = request.GET.get('country')
        if not country_name:
            messages.error(request, 'Ошибка создания ключа! Не указана страна в параметрах запроса.')
            return redirect('profile')

        country = get_object_or_404(Country, name=country_name)
        server = Server.objects.filter(is_active=True, country=country, keys_generated__lte=200).first()

        if not server:
            messages.error(request, f"Ошибка создания ключа! Нет доступных серверов для страны '{country.name}'.")
            return redirect('profile')

        user_profile = get_object_or_404(UserProfile, user=request.user)
        user = user_profile.telegram_user

        delete_user_keys(user=user)  # Удаляем текущие ключи
        new_key = create_new_key(server=server, user=user)  # Генерируем новый ключ
        messages.success(request, f'Новый ключ создан!\n{new_key}')
        Logging.objects.create(log_level=" INFO", message=f'[WEB] [Новый ключ создан]',
                               datetime=datetime.now(), user=self.request.user.profile.telegram_user)
        return redirect('profile')


class UpdateSubscriptionView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        subscription = request.GET.get('subscription')
        telegram_user_id = request.GET.get('telegram_user_id')
        if not subscription:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] Ошибка обновления подписки! SUB - [{subscription}] USER [{telegram_user_id}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            return redirect('profile')

        prices = Prices.objects.get(pk=1)
        amount = 0
        days = 0
        if float(subscription) == float(prices.price_1):
            amount = float(prices.price_1)
            days = 31
        elif float(subscription) == float(prices.price_2):
            amount = float(prices.price_2)
            days = 93
        elif float(subscription) == float(prices.price_3):
            amount = float(prices.price_3)
            days = 184
        elif float(subscription) == float(prices.price_4):
            amount = float(prices.price_4)
            days = 366

        if days and amount:
            user = get_object_or_404(TelegramUser, user_id=self.request.user.profile.telegram_user.user_id)
            user.balance = float(user.balance) - float(amount)
            if user.subscription_expiration < datetime.now():
                user.subscription_expiration = datetime.now()
            user.subscription_status = True
            user.subscription_expiration = user.subscription_expiration + timedelta(days=days)
            user.save()
            messages.success(request, f'Поздравляем с приобретением подписки! Подписка действительна до {user.subscription_expiration}')
            Logging.objects.create(log_level=" INFO", message=f'[WEB] [Приобретена подписка] [дни - {str(days)}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)
        else:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] Ошибка обновления подписки DAYS - [{str(days)}] AMOUNT [{str(amount)}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)

        return redirect('profile')