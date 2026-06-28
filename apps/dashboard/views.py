import traceback
from datetime import timedelta, datetime, date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.authentication.forms import DashboardPasswordChangeForm
from apps.mtproxy.services import can_use_mtproxy, get_active_key, issue_or_get_key, reissue_key, revoke_all_user_keys
from bot.main.vpn_key_issue import issue_vpn_key_for_user, logging_context_for_protocol
from bot.main.vpn_key_lock import acquire_vpn_key_create_lock, release_vpn_key_create_lock
from bot.models import VpnKey, Server, TelegramUser, Country, Prices, UserProfile, ReferralSettings, TelegramReferral, \
    Transaction, Logging, SiteNotification, SiteNotificationState

KEY_LIMIT = settings.KEY_LIMIT



class ProfileView(LoginRequiredMixin, SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/index.html'

    @staticmethod
    def _active_notifications_qs():
        now = timezone.now()
        return SiteNotification.objects.filter(
            is_active=True
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now)
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tg_user = self.request.user.profile.telegram_user
        notif_state, _ = SiteNotificationState.objects.get_or_create(user=tg_user)
        notifications_qs = self._active_notifications_qs()
        notifications = list(notifications_qs[:100])
        last_seen_id = int(notif_state.last_seen_notification_id or 0)
        unread_notifications = [n for n in notifications if n.id > last_seen_id]
        notifications_with_state = [
            {"obj": n, "is_unread": n.id > last_seen_id}
            for n in notifications
        ]

        context['servers'] = Server.objects.filter(is_active=True).values_list('country__name_for_app',

                                                                               flat=True).distinct()
        try:
            context['vpn_key'] = VpnKey.objects.select_related('user', 'server', 'server__country').get(user=tg_user)
        except VpnKey.DoesNotExist:
            context['vpn_key'] = None
        context['total_users'] = TelegramUser.objects.count()
        context['countries'] = Country.objects.filter(is_active=True)
        context['subscription'] = Prices.objects.get(id=1)
        context['referral'] = ReferralSettings.objects.get(pk=1)

        context['inv_1_lvl'] = TelegramReferral.objects.filter(referrer=tg_user, level=1).__len__()
        context['inv_2_lvl'] = TelegramReferral.objects.filter(referrer=tg_user, level=2).__len__()
        context['inv_3_lvl'] = TelegramReferral.objects.filter(referrer=tg_user, level=3).__len__()
        context['inv_4_lvl'] = TelegramReferral.objects.filter(referrer=tg_user, level=4).__len__()
        context['inv_5_lvl'] = TelegramReferral.objects.filter(referrer=tg_user, level=5).__len__()

        if tg_user.special_offer:
            context['per_1'] = tg_user.special_offer.level_1_percentage
            context['per_2'] = tg_user.special_offer.level_2_percentage
            context['per_3'] = tg_user.special_offer.level_3_percentage
            context['per_4'] = tg_user.special_offer.level_4_percentage
            context['per_5'] = tg_user.special_offer.level_5_percentage
        else:
            context['per_1'] = ReferralSettings.objects.get(pk=1).level_1_percentage
            context['per_2'] = ReferralSettings.objects.get(pk=1).level_2_percentage
            context['per_3'] = ReferralSettings.objects.get(pk=1).level_3_percentage
            context['per_4'] = ReferralSettings.objects.get(pk=1).level_4_percentage
            context['per_5'] = ReferralSettings.objects.get(pk=1).level_5_percentage


        context['transactions'] = Transaction.objects.filter(user=tg_user).order_by('-timestamp')
        context['dashboard_password_form'] = DashboardPasswordChangeForm(self.request.user)
        context['notifications'] = notifications_with_state
        context['last_seen_notification_id'] = last_seen_id
        context['unread_notifications_count'] = len(unread_notifications)
        context['latest_unread_notification'] = unread_notifications[0] if unread_notifications else None
        context['open_section'] = (self.request.GET.get('section') or '').strip()
        context['show_mtproxy'] = can_use_mtproxy(tg_user)
        if context['show_mtproxy']:
            context['mtproxy_key'] = get_active_key(tg_user)
        return context


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        tg_user = request.user.profile.telegram_user
        notification_id = int(kwargs.get('notification_id'))
        now = timezone.now()
        notification_exists = SiteNotification.objects.filter(
            id=notification_id,
            is_active=True
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now)
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).exists()
        if not notification_exists:
            return redirect('profile')

        state, _ = SiteNotificationState.objects.get_or_create(user=tg_user)
        if notification_id > state.last_seen_notification_id:
            state.last_seen_notification_id = notification_id
            state.save(update_fields=['last_seen_notification_id', 'updated_at'])

        return redirect('/dashboard/profile/?section=notifications')


class ManageMtProxyView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        tg_user = request.user.profile.telegram_user
        if not can_use_mtproxy(tg_user):
            return HttpResponseForbidden("Недостаточно прав для MTProto Proxy.")

        action = (request.POST.get("action") or "").strip()
        if action == "reissue":
            key = reissue_key(tg_user)
            if key:
                messages.success(request, "Новый MTProto ключ успешно создан.")
            else:
                messages.error(request, "Не удалось перевыдать ключ: нет доступных прокси-нод.")
        else:
            key, created = issue_or_get_key(tg_user)
            if key and created:
                messages.success(request, "MTProto ключ успешно создан.")
            elif key:
                messages.info(request, "У вас уже есть активный MTProto ключ.")
            else:
                messages.error(request, "Сейчас нет доступных прокси-нод.")

        return redirect("/dashboard/profile/?section=tg-proxy")


class CancelSubscriptionView(LoginRequiredMixin, TemplateView):

    def get(self, request, *args, **kwargs):
        user = TelegramUser.objects.filter(user_id=self.request.user.profile.telegram_user.user_id).first()
        user.payment_method_id = None
        user.robokassa_recurring_parent_inv_id = ''
        user.permission_revoked = True
        user.save()
        revoke_all_user_keys(user, reason="manual_cancel_site")
        Logging.objects.create(
            category="web",
            log_level=" INFO",
            message=f'[WEB] [Отмена подписки]',
            datetime=datetime.now(),
            user=self.request.user.profile.telegram_user
        )
        messages.success(request, f'Подписка отменена! Ежемесячная оплата отменена.')
        return redirect('profile')


class CreateNewKeyView(LoginRequiredMixin, View):
    _BUSY_MESSAGE = "Ключ уже создаётся. Подождите немного и обновите страницу."

    def _wants_json(self, request):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return True
        accept = request.headers.get("Accept") or ""
        return "application/json" in accept

    def _json(self, *, ok, message, busy=False, access_url=None, status=200):
        payload = {"ok": ok, "message": message, "busy": busy}
        if access_url:
            payload["access_url"] = access_url
        return JsonResponse(payload, status=status)

    def get(self, request, *args, **kwargs):
        messages.info(
            request,
            "Создание ключа выполняется через форму в личном кабинете. "
            "Если ключ уже создаётся — подождите и обновите страницу.",
        )
        return redirect("profile")

    def post(self, request, *args, **kwargs):
        country_name = (request.POST.get("country") or "").strip()
        protocol = (request.POST.get("protocol") or "").strip().lower()
        wants_json = self._wants_json(request)

        if not country_name or not protocol:
            message = "Ошибка создания ключа! Не указана страна или протокол."
            if wants_json:
                return self._json(ok=False, message=message, status=400)
            messages.error(request, message)
            return redirect("profile")

        country = get_object_or_404(Country, name=country_name)
        user_profile = get_object_or_404(UserProfile, user=request.user)
        user = user_profile.telegram_user

        if not acquire_vpn_key_create_lock(user.user_id):
            if wants_json:
                return self._json(ok=False, message=self._BUSY_MESSAGE, busy=True, status=409)
            messages.info(request, self._BUSY_MESSAGE)
            return redirect("profile")

        try:
            ok, message, access_url = issue_vpn_key_for_user(user, country, protocol)
            if ok:
                vpn_key = VpnKey.objects.filter(user=user).select_related("server", "server__country").first()
                server = vpn_key.server if vpn_key else None
                Logging.objects.create(
                    category="web",
                    log_level=" INFO",
                    message=(
                        f"[WEB] [Новый ключ создан] "
                        f"{logging_context_for_protocol(protocol, country, server)}"
                    ),
                    datetime=datetime.now(),
                    user=user,
                )
                if wants_json:
                    return self._json(ok=True, message=message, access_url=access_url)
                messages.success(request, message)
                return redirect("/dashboard/profile/?section=main-info")

            if wants_json:
                return self._json(ok=False, message=message, status=400)
            messages.error(request, message)
            return redirect("profile")
        except Exception:
            Logging.objects.create(
                category="web",
                log_level=" FATAL",
                message=f"[WEB] [ошибка создания ключа] [{protocol}] [{traceback.format_exc()}]",
                datetime=datetime.now(),
                user=user,
            )
            fatal_message = (
                "Ошибка создания ключа! На сервере возникли проблемы технического характера. "
                "Попробуйте позже или выберите другой протокол"
            )
            if wants_json:
                return self._json(ok=False, message=fatal_message, status=500)
            messages.error(request, fatal_message)
            return redirect("profile")
        finally:
            release_vpn_key_create_lock(user.user_id)


class UpdateSubscriptionView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        subscription = request.GET.get('subscription')
        telegram_user_id = request.GET.get('telegram_user_id')
        if not subscription:
            Logging.objects.create(category="web", log_level="DANGER",
                                   message=f'[WEB] Ошибка обновления подписки! SUB - [{subscription}] USER [{telegram_user_id}]',
                                   datetime=datetime.now(), user=self.request.user.profile.telegram_user)
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
                messages.success(request,
                                 f'Поздравляем с приобретением подписки! Подписка действительна до {user.subscription_expiration}')
                Logging.objects.create(category="web", log_level=" INFO", message=f'[WEB] [Приобретена подписка] [дни - {str(days)}]',
                                       datetime=datetime.now(), user=self.request.user.profile.telegram_user)
            else:
                messages.error(request, f'У вас недостаточно средств на балансе для выбранной подписки 😐')

        else:
            Logging.objects.create(category="web", log_level="DANGER",
                                   message=f'[WEB] Ошибка обновления подписки DAYS - [{str(days)}] AMOUNT [{str(amount)}]',
                                   datetime=datetime.now(), user=self.request.user.profile.telegram_user)

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
