from datetime import timedelta, datetime, date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from bot.main.MarzbanAPI import MarzbanAPI
from bot.models import VpnKey, Server, TelegramUser, Country, Prices, UserProfile, ReferralSettings, TelegramReferral, \
    Transaction, Logging

KEY_LIMIT = settings.KEY_LIMIT
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

        if self.request.user.profile.telegram_user.special_offer:
            context['per_1'] = self.request.user.profile.telegram_user.special_offer.level_1_percentage
            context['per_2'] = self.request.user.profile.telegram_user.special_offer.level_2_percentage
            context['per_3'] = self.request.user.profile.telegram_user.special_offer.level_3_percentage
            context['per_4'] = self.request.user.profile.telegram_user.special_offer.level_4_percentage
            context['per_5'] = self.request.user.profile.telegram_user.special_offer.level_5_percentage
        else:
            context['per_1'] = ReferralSettings.objects.get(pk=1).level_1_percentage
            context['per_2'] = ReferralSettings.objects.get(pk=1).level_2_percentage
            context['per_3'] = ReferralSettings.objects.get(pk=1).level_3_percentage
            context['per_4'] = ReferralSettings.objects.get(pk=1).level_4_percentage
            context['per_5'] = ReferralSettings.objects.get(pk=1).level_5_percentage

        context['transactions'] = Transaction.objects.filter(user=self.request.user.profile.telegram_user).order_by('-timestamp')
        return context

class CancelSubscriptionView(LoginRequiredMixin, TemplateView):

    def get(self, request, *args, **kwargs):
        user = TelegramUser.objects.filter(user_id=self.request.user.profile.telegram_user.user_id).first()
        user.payment_method_id = None
        user.permission_revoked = True
        user.save()
        Logging.objects.create(
            log_level=" INFO",
            message=f'[WEB] [Отмена подписки]',
            datetime=datetime.now(),
            user=self.request.user.profile.telegram_user
        )
        messages.success(request, f'Подписка отменена! Ежемесячная оплата отменена.')
        return redirect('profile')

class CreateNewKeyView(LoginRequiredMixin, TemplateView):

    def get(self, request, *args, **kwargs):
        country_name = request.GET.get('country')
        protocol = request.GET.get('protocol')
        if not country_name or not protocol:
            messages.error(request, 'Ошибка создания ключа! Не указана страна или протокол в параметрах запроса.')
            return redirect('profile')

        country = get_object_or_404(Country, name=country_name)


        user_profile = get_object_or_404(UserProfile, user=request.user)
        user = user_profile.telegram_user

        if protocol == 'outline':

            server = Server.objects.filter(is_active=True, is_activated_vless=True, country=country,
                                           keys_generated__lte=KEY_LIMIT).order_by('keys_generated').first()
            if not server:
                messages.error(request, f"Ошибка создания ключа! Нет доступных серверов для страны '{country.name}'.")
                return redirect('profile')


            VpnKey.objects.filter(user=user).delete() #  Удаляем все предыдущие ключи

            MarzbanAPI().create_user(username=str(user.user_id)) # Генерируем новый ключ vless
            success, result = MarzbanAPI().get_user(username=str(user.user_id))
            links = result['links']
            key = "---"

            for link in links:
                if server.ip_address in link and "ss://" in link:
                    key = link
                    break

            VpnKey.objects.create(server=server, user=user, key_id=user.user_id,
                                        name=str(user.user_id), password=str(user.user_id),
                                        port=1040, method='ss', access_url=key, protocol='outline')

            messages.success(request, f'Новый ключ создан!')
            Logging.objects.create(log_level=" INFO", message=f'[WEB] [Новый ключ создан]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)

        elif protocol == 'vless':

            server = Server.objects.filter(is_active=True, is_activated_vless=True, country=country,
                                           keys_generated__lte=KEY_LIMIT).order_by('keys_generated').first()
            if not server:
                messages.error(request, f"Ошибка создания ключа! Нет доступных серверов для страны '{country.name}'.")
                return redirect('profile')


            VpnKey.objects.filter(user=user).delete() #  Удаляем все предыдущие ключи

            MarzbanAPI().create_user(username=str(user.user_id)) # Генерируем новый ключ vless
            success, result = MarzbanAPI().get_user(username=str(user.user_id))
            links = result['links']
            key = "---"
            for link in links:

                if server.ip_address in link and "vless://" in link:
                    key = link
                    break

            VpnKey.objects.create(server=server, user=user, key_id=user.user_id,
                                        name=str(user.user_id), password=str(user.user_id),
                                        port=1040, method='vless', access_url=key, protocol='vless')

            messages.success(request, f'Новый ключ создан!')
            Logging.objects.create(log_level=" INFO", message=f'[WEB] [Новый ключ создан]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)
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
            if float(user.balance) >= float(amount):
                user.balance = float(user.balance) - float(amount)
                if user.subscription_expiration < date.today():
                    user.subscription_expiration = date.today()
                user.subscription_status = True
                user.subscription_expiration = user.subscription_expiration + timedelta(days=days)
                user.save()
                messages.success(request, f'Поздравляем с приобретением подписки! Подписка действительна до {user.subscription_expiration}')
                Logging.objects.create(log_level=" INFO", message=f'[WEB] [Приобретена подписка] [дни - {str(days)}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            else:
                messages.error(request,f'У вас недостаточно средств на балансе для выбранной подписки 😐')

        else:
            Logging.objects.create(log_level="DANGER", message=f'[WEB] Ошибка обновления подписки DAYS - [{str(days)}] AMOUNT [{str(amount)}]', datetime=datetime.now(), user=self.request.user.profile.telegram_user)

        return redirect('profile')



@login_required
def daily_transaction_analytics(request):
    """
    Calculates the sum of successful transactions for each day and returns the data
    in a format suitable for Chart.js.
    """
    SUCCESS_STATUS = 'succeeded'

    daily_successful_transactions = Transaction.objects.filter(
        status=SUCCESS_STATUS
    ).annotate(
        date=TruncDate('timestamp')
    ).values('date').annotate(
        total_amount=Sum('amount')
    ).order_by('date')

    labels = [item['date'].strftime('%Y-%m-%d') for item in daily_successful_transactions]
    data = [float(item['total_amount']) for item in daily_successful_transactions]

    chart_data = {
        'labels': labels,
        'datasets': [{
            'label': 'Сумма успешных транзакций',
            'data': data,
            'backgroundColor': 'rgba(54, 162, 235, 0.5)',
            'borderColor': 'rgba(54, 162, 235, 1)',
            'borderWidth': 1
        }]
    }

    # If it's an AJAX request (e.g., for API endpoints, though not strictly used here for initial render)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(chart_data)

    context = {
        'chart_data_json': chart_data,
        'status_filter': SUCCESS_STATUS,
    }
    if request.user.is_superuser:
        return render(request, 'dashboard/analytics.html', context)
    else:
        return redirect('home')