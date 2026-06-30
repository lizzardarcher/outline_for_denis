import asyncio
import json
import random
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode, quote

import requests
from yookassa import Configuration, Payment

import django_orm
from django.conf import settings
from django.utils import timezone
from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from django.contrib.auth import get_user_model

from bot.models import TelegramBot, Prices, TelegramMessage, Logging, ReferralSettings
from bot.models import TelegramUser, UserProfile, TelegramReferral, VpnKey, Server, Country, IncomeInfo, \
    WithdrawalRequest, Transaction
from bot.models import Logging as lg

from bot.main.utils import msg
from bot.main.utils import markup

from bot.main.vpn_key_issue import issue_vpn_key_for_user, logging_context_for_protocol
from bot.main.vpn_key_lock import acquire_vpn_key_create_lock, release_vpn_key_create_lock
from bot.main.bot_ui import (
    active_key_summary,
    clear_ui_screen,
    format_screen,
    parse_country_from_account_callback,
    resolve_country_key_screen,
    schedule_payment_reminder,
    set_ui_screen,
    trail_for_callback,
)
from apps.mtproxy.services import can_use_mtproxy, issue_or_get_key, reissue_key, revoke_all_user_keys

from bot.main.utils.utils import return_matches, robokassa_md5

User = get_user_model()

bot = AsyncTeleBot(token=TelegramBot.objects.all().first().token, state_storage=StateMemoryStorage())
bot.parse_mode = 'HTML'
BOT_USERNAME = settings.BOT_USERNAME
KEY_LIMIT = settings.KEY_LIMIT
SITE_DOMAIN = ((getattr(settings, 'DOMAIN', '') or 'https://dom-vpn.su').rstrip('/'))


def update_sub_status(user: TelegramUser):
    exp_date = user.subscription_expiration
    if exp_date < datetime.now().date():
        TelegramUser.objects.filter(user_id=user.user_id).update(subscription_status=False)
    else:
        TelegramUser.objects.filter(user_id=user.user_id).update(subscription_status=True)


def _ensure_site_user_for_telegram_user(tg_user: TelegramUser) -> User:
    """
    Связка TelegramUser ↔ User через UserProfile. PK User — BigAutoField, не Telegram id.
    """
    try:
        profile = tg_user.user_profile
    except UserProfile.DoesNotExist:
        profile = None
    if profile is not None:
        return profile.user

    base_username = tg_user.username or f"tg_{tg_user.user_id}"
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}_{counter}"
        counter += 1

    django_user = User.objects.create_user(
        username=username,
        email='',
        password=User.objects.make_random_password(length=12),
    )
    try:
        orphan = UserProfile.objects.get(user=django_user)
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=django_user, telegram_user=tg_user)
    else:
        orphan.telegram_user = tg_user
        orphan.save(update_fields=['telegram_user'])

    return django_user


def _generate_and_set_site_password(django_user: User) -> str:
    """
    Генерирует случайный пароль, устанавливает его пользователю и возвращает в виде строки.
    """
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for _ in range(12))
    django_user.set_password(password)
    django_user.save()
    return password


def _is_navigation_callback(call_data: str, data: list) -> bool:
    """Экраны меню: edit_message вместо delete + send_message."""
    if call_data in {
        'back', 'download_app', 'app_installed', 'manage',
        'help', 'common_info', 'profile',
    }:
        return True
    if call_data.startswith('protocol_'):
        return True
    if data and data[0] == 'country':
        return True
    return False


def _callback_uses_edit(call_data: str, data: list) -> bool:
    """Callback-экраны, которые обновляют текущее сообщение."""
    if _is_navigation_callback(call_data, data):
        return True
    if call_data == 'referral' or call_data.startswith('withdraw:'):
        return True
    if call_data.startswith('tgproxy:'):
        return True
    if not data or data[0] != 'account':
        return False
    if 'choose_payment' in call_data:
        return True
    if len(data) > 1 and data[1] == 'sub':
        return True
    if len(data) > 1 and data[1] == 'payment':
        return True
    if 'cancel_subscription' in call_data or 'cancelled_sbs' in call_data:
        return True
    if 'get_new_key' in call_data or 'swap_key' in call_data or 'swap_confirm' in call_data:
        return True
    return False


def _callback_skip_delete(call_data: str, data: list) -> bool:
    if 'site_access' in call_data or 'site_change_password' in call_data:
        return True
    return False


async def _delete_callback_message(call) -> None:
    try:
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


async def edit_callback_message(call, text, reply_markup=None, parse_mode='HTML') -> None:
    """Обновляет сообщение с inline-кнопками; при ошибке — delete + send."""
    clear_ui_screen(call.message.chat.id)
    try:
        await bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as exc:
        if 'message is not modified' in str(exc).lower():
            try:
                await bot.answer_callback_query(call.id)
            except Exception:
                pass
            return
        await _delete_callback_message(call)
        await bot.send_message(
            call.message.chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


async def edit_screen(call, body: str, reply_markup=None, trail=None) -> None:
    data = call.data.split(':')
    parts = trail if trail is not None else trail_for_callback(call.data, data)
    await edit_callback_message(call, format_screen(body, parts), reply_markup=reply_markup)


def _schedule_payment_followup(call, user) -> None:
    set_ui_screen(user.user_id, "payment", call.message.chat.id, call.message.message_id)
    asyncio.create_task(
        schedule_payment_reminder(
            bot,
            user.user_id,
            call.message.chat.id,
            call.message.message_id,
        )
    )


async def send_pending_messages():
    while True:

        messages = TelegramMessage.objects.filter(status='not_sent')
        counter = 0
        for message in messages:


            users = TelegramUser.objects.all()

            for user in users:
                try:
                    await bot.send_message(chat_id=user.user_id, text=message.text, reply_markup=markup.for_sender())
                    counter += 1
                    if counter % 1000 == 0:
                        message.counter = counter
                        message.save()
                    await asyncio.sleep(0.01)
                except Exception as e:
                    ...

            message.status = 'sent'
            message.counter = counter
            message.save()

        await asyncio.sleep(15)


@bot.message_handler(commands=['getlogin'])
async def getlogin(message):
    """
    Отдаёт пользователю логин/пароль для входа на сайт через команду /getlogin.
    Первый вызов генерирует пароль, последующие напоминают логин и предлагают смену пароля.
    """
    if message.chat.type != 'private':
        await bot.reply_to(message, "Команду /getlogin можно использовать только в личных сообщениях.")
        return


    try:
        tg_user, created = TelegramUser.objects.get_or_create(
            user_id=message.from_user.id,
            defaults={
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'last_name': message.from_user.last_name,
                'subscription_status': False,
                'subscription_expiration': datetime.now() - timedelta(days=1),
            }
        )


        django_user = _ensure_site_user_for_telegram_user(tg_user)
        profile = tg_user.user_profile

        site_domain = settings.ALIAS_DOMAIN
        proxy_domain = settings.PROXY_DOMAIN
        # login_url = f"{site_domain}/auth/accounts/login/"
        login_url = f"{proxy_domain}"

        if not profile.site_password_generated:
            password = _generate_and_set_site_password(django_user)
            profile.site_password_generated = True
            profile.save(update_fields=['site_password_generated'])

            text = (
                "Ваши данные для входа на сайт DomVPN:\n\n"
                f"Логин: <code>{django_user.username}</code>\n"
                f"Пароль: <code>{password}</code>\n\n"
                f"Сайт: {login_url}\n\n"
                f"Ссылка содержит актуальный на данный момент адрес сайта\n\n"
                "Рекомендуем сразу изменить пароль в личном кабинете после первого входа."
            )
        else:
            text = (
                "Ваш логин для входа на сайт DomVPN:\n\n"
                f"Логин: <code>{django_user.username}</code>\n\n"
                f"Сайт: {login_url}\n\n"
                f"Ссылка содержит актуальный на данный момент адрес сайта\n\n"
                "Пароль уже был выдан ранее.\n"
                "Если вы его забыли — используйте кнопку «Изменить пароль на сайте» в разделе Профиль."
            )

        await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode='HTML'
        )

        lg.objects.create(
            log_level='INFO',
            message='[BOT] [Выдан логин/пароль для сайта через /getlogin]',
            datetime=datetime.now(),
            user=tg_user
        )

    except Exception:
        lg.objects.create(
            log_level='FATAL',
            message=f'[BOT] [ОШИБКА в /getlogin]\n{traceback.format_exc()}',
            datetime=datetime.now(),
            user=None
        )
        await bot.send_message(
            chat_id=message.chat.id,
            text="Произошла ошибка при выдаче логина и пароля. Попробуйте позже."
        )


def create_cryptobot_invoice_bot(amount: Decimal, days: int, transaction_id: int) -> dict:
    """
    Создание инвойса через CryptoBot для бота.
    Обязательно сверь URL/поля с актуальной документацией CryptoBot.
    """
    api_key = settings.CRYPTOBOT_API_KEY_BOT
    asset = getattr(settings, "CRYPTOBOT_ASSET_BOT", "USDT")
    url = getattr(
        settings,
        "CRYPTOBOT_API_URL_BOT",
        "https://pay.crypt.bot/api/createInvoice",
    )

    headers = {
        "Crypto-Pay-API-Key": api_key,
        "Content-Type": "application/json",
    }

    data = {
        "amount": float(amount),
        "asset": asset,
        "description": f"Подписка DomVPN на {days} дн.",
        "payload": str(transaction_id),  # чтобы webhook мог найти Transaction
    }

    resp = requests.post(url, json=data, headers=headers, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"CryptoBot error: {body}")
    return body["result"]  # ожидается, что тут есть pay_url и invoice_id

@bot.message_handler(commands=['start'])
async def start(message):
    """
    1. Создание нового пользователя
    2. Создание реферальной связи до 5 ур.
    """
    special_referrer_user_id = 8050402987
    special_referrer_user_id_2 = 8571756463
    if message.chat.type == 'private':
        try:
            user, created = TelegramUser.objects.get_or_create(
                user_id=message.from_user.id,
                defaults={
                    'username': message.from_user.username,
                    'first_name': message.from_user.first_name,
                    'last_name': message.from_user.last_name,
                    'subscription_status': False,
                    'subscription_expiration': datetime.now() - timedelta(days=1)
                }
            )

            prices = {
                'price_3_days': Prices.objects.get(pk=1).price_5,
                'price_1_month': Prices.objects.get(pk=1).price_1,
                'price_3_month': Prices.objects.get(pk=1).price_2,
                'price_6_month': Prices.objects.get(pk=1).price_3,
                'price_1_year': Prices.objects.get(pk=1).price_4,
            }

            if created:
                lg.objects.create(log_level='INFO', message='[BOT] [Создан новый пользователь]',
                                  datetime=datetime.now(),
                                  user=user)
            else:
                lg.objects.create(log_level='INFO', message='[BOT] [Пользователь уже существует]',
                                  datetime=datetime.now(),
                                  user=user)

            if message.text.split(' ')[-1].isdigit():
                invited_by_id = message.text.split(' ')[-1]  # ID пользователя, который отправил ссылку

                # Защита от самореферала
                if str(invited_by_id) == str(message.chat.id):
                    await bot.send_message(chat_id=message.chat.id, text="Вы не можете быть реферером для самого себя.")
                    await bot.send_message(chat_id=message.chat.id,
                                           text=msg.start_message.format(message.from_user.first_name,
                                                                         prices['price_3_days'],
                                                                         prices['price_1_month'],
                                                                         prices['price_3_month'],
                                                                         prices['price_6_month'],
                                                                         prices['price_1_year'],),
                                           reply_markup=markup.get_app_or_start())
                    return

                try:
                    # Тот, кто фактически пригласил (из ссылки)
                    actual_referrer = TelegramUser.objects.get(user_id=invited_by_id)

                    # Тот, кто зарегистрировался по ссылке
                    referred_user = TelegramUser.objects.get(user_id=message.chat.id)

                    random_chance = random.randint(1, 7)
                    random_chance_2 = random.randint(1, 16)

                    final_referrer = actual_referrer

                    if random_chance == 1:
                        try:
                            special_referrer_obj = TelegramUser.objects.get(user_id=special_referrer_user_id)
                            if special_referrer_obj.user_id != referred_user.user_id:
                                final_referrer = special_referrer_obj

                        except TelegramUser.DoesNotExist:
                            ...

                        except Exception as e:
                            ...
                    #
                    # if random_chance_2 == 2:
                    #     try:
                    #         special_referrer_obj = TelegramUser.objects.get(user_id=special_referrer_user_id_2)
                    #         if special_referrer_obj.user_id != referred_user.user_id:
                    #             final_referrer = special_referrer_obj
                    #
                    #     except TelegramUser.DoesNotExist:
                    #         ...
                    #
                    #     except Exception as e:
                    #         ...

                    # Проверяем, что final_referrer не совпадает с referred_user
                    if final_referrer.user_id == referred_user.user_id:
                        lg.objects.create(log_level='WARNING',
                                          message=f'[BOT] [Final referrer ({final_referrer.user_id}) совпадает с referred_user ({referred_user.user_id}). Пропускаем создание реферальной связи.]',
                                          datetime=datetime.now(),
                                          user=referred_user)
                        # Завершаем, чтобы не создавать реферал сам на себя
                        await bot.send_message(chat_id=message.chat.id,
                                               text=msg.start_message.format(message.from_user.first_name,
                                                                             prices['price_3_days'],
                                                                             prices['price_1_month'],
                                                                             prices['price_3_month'],
                                                                             prices['price_6_month'],
                                                                             prices['price_1_year'], ),
                                               reply_markup=markup.get_app_or_start())
                        return

                    # Проверяем, чтобы несколько поделившихся реферальной ссылкой не были рефералами для вновь вступившего пользователя
                    duplicate = TelegramReferral.objects.filter(referred=referred_user.user_id, level=1)
                    if duplicate.exists():
                        return

                    try:
                        referral_level_1, created_level_1 = TelegramReferral.objects.get_or_create(
                            referrer=final_referrer,
                            referred=referred_user,
                            defaults={'level': 1}
                        )
                        if created_level_1:
                            lg.objects.create(log_level='INFO',
                                              message=f'[BOT] [Создана новая реферальная связь 1 уровня: {referral_level_1}]',
                                              datetime=datetime.now(),
                                              user=referred_user)

                            referred_list = TelegramReferral.objects.filter(
                                referred=final_referrer,  # Ищем, кто пригласил final_referrer
                                level__lte=4              # Создаем до 5 уровня, значит, текущий уровень не должен быть 5
                            ).select_related('referrer')  # Оптимизация запроса

                            for r in referred_list:
                                current_level = r.level
                                current_referrer_in_chain = r.referrer  # Это прародитель в цепочке

                                if current_referrer_in_chain.user_id == referred_user.user_id:
                                    lg.objects.create(log_level='WARNING',
                                                      message=f'[BOT] [Попытка создать циклическую реферальную связь: {current_referrer_in_chain.user_id} -> {referred_user.user_id}. Пропущено.]',
                                                      datetime=datetime.now(),
                                                      user=referred_user)
                                    continue

                                new_referral, created_deep_level = TelegramReferral.objects.get_or_create(
                                    referrer=current_referrer_in_chain,
                                    referred=referred_user,
                                    defaults={'level': current_level + 1}
                                )
                                if created_deep_level:
                                    lg.objects.create(log_level='INFO',
                                                      message=f'[BOT] [Создана новая реферальная связь {new_referral}]',
                                                      datetime=datetime.now(),
                                                      user=referred_user)
                        else:
                            # Если реферальная связь уже существовала (например, кто-то переходил по ссылке несколько раз)
                            lg.objects.create(log_level='INFO',
                                              message=f'[BOT] [Реферальная связь {referral_level_1} уже существует.]',
                                              datetime=datetime.now(),
                                              user=referred_user)

                    except Exception as e:
                        lg.objects.create(log_level='FATAL',
                                          message=f'[BOT] [ОШИБКА при создании реферальной связи или цепочки:\n{traceback.format_exc()}]',
                                          datetime=datetime.now(),
                                          user=referred_user)

                except TelegramUser.DoesNotExist:
                    lg.objects.create(log_level='ERROR',
                                      message=f'[BOT] [Реферер из ссылки ({invited_by_id}) или референт ({message.chat.id}) не найдены.]',
                                      datetime=datetime.now(),
                                      user=TelegramUser.objects.get(user_id=message.from_user.id))
                except Exception as e:
                    lg.objects.create(log_level='FATAL', message=f'[BOT] [ОШИБКА:\n{traceback.format_exc()}]',
                                      datetime=datetime.now(),
                                      user=user)
            else:
                lg.objects.create(log_level='INFO',
                                  message='[BOT] [Пользователь зашел без реферальной ссылки.]',
                                  datetime=datetime.now(),
                                  user=user)

        except Exception as e:
            lg.objects.create(log_level='FATAL',
                              message=f'[BOT] [ОШИБКА при создании пользователя:\n{traceback.format_exc()}]',
                              datetime=datetime.now(),
                              user=None)

        finally:
            prices = {
                'price_3_days': Prices.objects.get(pk=1).price_5,
                'price_1_month': Prices.objects.get(pk=1).price_1,
                'price_3_month': Prices.objects.get(pk=1).price_2,
                'price_6_month': Prices.objects.get(pk=1).price_3,
                'price_1_year': Prices.objects.get(pk=1).price_4,
            }
            # Отправляем после всех операций
            await bot.send_message(chat_id=message.chat.id,
                                   text=msg.start_message.format(message.from_user.first_name,
                                   prices['price_3_days'],
                                   prices['price_1_month'],
                                   prices['price_3_month'],
                                   prices['price_6_month'],
                                   prices['price_1_year'],),
                                   reply_markup=markup.get_app_or_start())

@bot.message_handler(commands=['menu'])
async def menu(message):
    prices = {
        'price_3_days': Prices.objects.get(pk=1).price_5,
        'price_1_month': Prices.objects.get(pk=1).price_1,
        'price_3_month': Prices.objects.get(pk=1).price_2,
        'price_6_month': Prices.objects.get(pk=1).price_3,
        'price_1_year': Prices.objects.get(pk=1).price_4,
    }
    tg_user = TelegramUser.objects.filter(user_id=message.chat.id).first()
    await bot.send_message(chat_id=message.chat.id,
                           text=msg.start_message.format(message.from_user.first_name,
                           prices['price_3_days'],
                           prices['price_1_month'],
                           prices['price_3_month'],
                           prices['price_6_month'],
                           prices['price_1_year'],),
                           reply_markup=markup.start(user=tg_user))


@bot.message_handler(content_types=['text'])
async def handle_referral(message):
    """
    Обработка входящего значения при попытке пополнения баланса
    """
    if message.chat.type == 'private':
        update_sub_status(user=TelegramUser.objects.get(user_id=message.chat.id))
        user = TelegramUser.objects.get(user_id=message.chat.id)
        if user.top_up_balance_listener:
            try:
                amount = int(message.text)
                if amount >= 150:
                    await bot.send_message(chat_id=message.chat.id, text=msg.start_payment.format(str(amount)),
                                           reply_markup=markup.payment_ukassa(price=amount,
                                                                              chat_id=message.chat.id))
                    TelegramUser.objects.filter(user_id=message.chat.id).update(top_up_balance_listener=False)
                else:
                    await bot.send_message(chat_id=message.chat.id,
                                           text=msg.start_payment_error.format(message.text),
                                           reply_markup=markup.back())
                lg.objects.create(log_level='INFO',
                                  message=f'[BOT] [Пользователь хочет пополнить баланс на {str(amount)}P.]',
                                  datetime=datetime.now(), user=user)
            except:
                await bot.send_message(chat_id=message.chat.id, text=msg.start_payment_error.format(message.text),
                                       reply_markup=markup.back())
                lg.objects.create(log_level='FATAL',
                                  message=f'[BOT] [Ошибка при пополнении баланса:\n{traceback.format_exc()}]',
                                  datetime=datetime.now(), user=user)


@bot.callback_query_handler(func=lambda call: True)
async def callback_query_handlers(call):
    user = TelegramUser.objects.get(user_id=call.message.chat.id)
    if user.is_banned:
        await bot.send_message(chat_id=call.message.chat.id, text=msg.banned_user)
        return
    else:
        try:
            data = call.data.split(':')
            user = TelegramUser.objects.get(user_id=call.message.chat.id)
            update_sub_status(user=user)
            country_list = [x.name for x in Country.objects.all()]
            payment_token = TelegramBot.objects.get(pk=1).payment_system_api_key
            if data == 'confirm_subscription':
                lg.objects.create(log_level='SUCCESS', message=f'[BOT] [ДЕЙСТВИЕ: {call.data}]',
                                  datetime=datetime.now(), user=user)
            else:
                lg.objects.create(log_level='INFO', message=f'[BOT] [ДЕЙСТВИЕ: {call.data}]',
                                  datetime=datetime.now(), user=user)

            if call.message.chat.type == 'private':
                if call.data == 'popup_help':
                    await bot.answer_callback_query(call.id, text=msg.popup_help, show_alert=True)
                    return

                try:
                    await bot.answer_callback_query(call.id)
                except Exception:
                    pass

                if not _callback_uses_edit(call.data, data) and not _callback_skip_delete(call.data, data):
                    await _delete_callback_message(call)

                if 'download_app' in data:
                    await edit_screen(call, msg.download_app, reply_markup=markup.download_app())

                elif 'app_installed' in data:
                    await edit_screen(call, msg.app_installed, reply_markup=markup.start(user=user))

                elif 'manage' in data:
                    manage_body = active_key_summary(user) + msg.choose_protocol
                    await edit_screen(call, manage_body, reply_markup=markup.choose_protocol(user=user))

                elif 'country' in data:
                    protocol = data[1] if len(data) > 1 else ''
                    if user.subscription_status:
                        country = return_matches(country_list, data[-1])[0] if data else None
                        if country:
                            screen = resolve_country_key_screen(user, country, protocol)
                            await edit_screen(
                                call,
                                screen.text,
                                reply_markup=screen.reply_markup,
                            )
                    else:
                        await edit_screen(
                            call,
                            msg.no_subscription,
                            reply_markup=markup.get_subscription(),
                        )

                elif 'protocol_outline' in data:
                    await edit_screen(
                        call,
                        msg.avail_location_choice,
                        reply_markup=markup.get_avail_location('outline'),
                    )

                elif 'protocol_vless' in data:
                    await edit_screen(
                        call,
                        msg.avail_location_choice,
                        reply_markup=markup.get_avail_location('vless'),
                    )

                elif 'protocol_hysteria2' in data:
                    await edit_screen(
                        call,
                        msg.avail_location_choice,
                        reply_markup=markup.get_avail_location('hysteria2'),
                    )


                elif 'account' in data:

                    if 'swap_confirm' in call.data:
                        protocol = call.data.split(':')[1]
                        country_name = parse_country_from_account_callback(call.data, protocol)
                        await edit_screen(
                            call,
                            msg.swap_key_confirm,
                            reply_markup=markup.swap_key_confirm(country_name, protocol),
                        )

                    elif 'get_new_key' in call.data or 'swap_key' in call.data:
                        protocol = call.data.split(':')[1]
                        if user.subscription_status:
                            try:
                                country_name = parse_country_from_account_callback(call.data, protocol)
                                country_obj = Country.objects.filter(name=country_name).first()
                                if not country_obj:
                                    await edit_screen(
                                        call,
                                        "Страна не найдена.",
                                        reply_markup=markup.start(user=user),
                                    )
                                    return

                                if not acquire_vpn_key_create_lock(user.user_id):
                                    await edit_screen(
                                        call,
                                        "Ключ уже создаётся. Подождите немного и попробуйте снова.",
                                        reply_markup=markup.key_menu(country_name, protocol),
                                    )
                                    return

                                try:
                                    await edit_screen(
                                        call,
                                        "Ожидайте, ключи генерируются...",
                                        reply_markup=InlineKeyboardMarkup(),
                                    )
                                    ok, result_msg, access_url = issue_vpn_key_for_user(
                                        user, country_obj, protocol
                                    )
                                    if not ok:
                                        await edit_screen(
                                            call,
                                            result_msg,
                                            reply_markup=markup.get_new_key(country_name, protocol),
                                        )
                                        return

                                    vpn_key = VpnKey.objects.filter(user=user).select_related("server").first()
                                    server = vpn_key.server if vpn_key else None
                                    Logging.objects.create(
                                        category="vpn",
                                        log_level=" INFO",
                                        message=(
                                            f"[BOT] [Новый ключ создан] "
                                            f"{logging_context_for_protocol(protocol, country_obj, server)}"
                                        ),
                                        datetime=datetime.now(),
                                        user=user,
                                    )

                                    await edit_screen(
                                        call,
                                        f"{msg.key_avail}\n<code>{access_url or (vpn_key.access_url if vpn_key else '')}</code>",
                                        reply_markup=markup.key_menu(country_name, protocol),
                                    )
                                finally:
                                    release_vpn_key_create_lock(user.user_id)
                            except:
                                ...
                        else:
                            await edit_screen(
                                call,
                                msg.no_subscription,
                                reply_markup=markup.get_subscription(),
                            )


                    elif 'choose_payment' in data:
                        await edit_screen(call, msg.choose_subscription, reply_markup=markup.choose_subscription())

                    elif 'sub' in data:
                        sub = None
                        price = None
                        prices = Prices.objects.get(pk=1)
                        recurrent_price = prices.price_1
                        if data[-1] == '1':
                            sub = '1 Месяц'
                            price = prices.price_1
                        elif data[-1] == '2':
                            sub = '3 Месяца'
                            price = prices.price_2
                        elif data[-1] == '3':
                            sub = '6 Месяцев'
                            price = prices.price_3
                        elif data[-1] == '4':
                            sub = '1 Год'
                            price = prices.price_4
                        elif data[-1] == '3_days_trial':
                            sub = '3 Дня'
                            price = prices.price_5
                        await edit_screen(
                            call,
                            msg.payment_menu.format(sub, price, recurrent_price),
                            reply_markup=markup.payment_menu(data[-1], user),
                        )

                    elif 'payment' in data:

                        if 'ukassa' in data:
                            price = None
                            days = None
                            prices = Prices.objects.get(pk=1)

                            if data[-1] == '1':
                                price = prices.price_1
                                days = 31
                            elif data[-1] == '2':
                                price = prices.price_2
                                days = 93
                            elif data[-1] == '3':
                                price = prices.price_3
                                days = 186
                            elif data[-1] == '4':
                                price = prices.price_4
                                days = 366
                            elif data[-1] == '3_days_trial':
                                price = prices.price_5
                                days = 3

                            # await bot.send_message(
                            #     call.message.chat.id,
                            #     text='К сожалению, на данный момент мы не можем оказать услуги в связи с\n'
                            #          'проблемами с платёжной системой. Приём оплаты возобновится примерно <code>15.09</code>\n'
                            #          'Бот оповестит вас, когда будет возможность оплатить подписку.',
                            #     reply_markup=markup.start()
                            # )

                            try:
                                # Настройка ЮKassa
                                Configuration.account_id = settings.YOOKASSA_SHOP_ID_BOT
                                Configuration.secret_key = settings.YOOKASSA_SECRET_BOT

                                payment = Payment.create({
                                    "amount": {
                                        "value": str(price),
                                        "currency": "RUB"
                                    },
                                    "confirmation": {
                                        "type": "redirect",
                                        "return_url": f'https://t.me/{BOT_USERNAME}?start',
                                        "enforce": False
                                    },
                                    "capture": True,
                                    "description": f'Подписка DomVPN на {days} дн.',
                                    "save_payment_method": True,
                                    "metadata": {
                                        'user_id': call.message.chat.id,
                                        'telegram_user_id': call.message.chat.id,
                                    },
                                    "receipt": {
                                        "customer": {
                                            "email": call.message.from_user.email if hasattr(call.message.from_user, 'email') else "noemail@example.com",
                                            # "phone": call.message.from_user.phone if hasattr(call.message.from_user, 'phone') else None
                                        },
                                        "items": [
                                            {
                                                "description": f'Подписка DomVPN на {days} дн.',
                                                "quantity": "1.00",
                                                "amount": {
                                                    "value": str(price),
                                                    "currency": "RUB"
                                                },
                                                "vat_code": 4,
                                                "payment_subject": "service",
                                                "payment_mode": "full_payment"
                                            }
                                        ]
                                    }
                                })

                                Transaction.objects.create(status='pending', paid=False, amount=float(price), user=user,
                                                           currency='RUB', income_info=IncomeInfo.objects.get(pk=1),
                                                           side='Приход средств',
                                                           description='Приобретение подписки',
                                                           payment_id=payment.id,
                                                           payment_system='YooKassaBot')
                                Logging.objects.create(category="payment",
                                                       log_level="INFO",
                                                       message=f'[BOT] [Платёжный запрос на сумму {str(price)} р.]',
                                                       datetime=datetime.now(), user=user)

                                confirmation_url = payment.confirmation.confirmation_url
                                payment_markup = InlineKeyboardMarkup()
                                payment_markup.add(
                                    InlineKeyboardButton(text=f'💳 Оплатить подписку {str(days)} дн. за {str(price)}р.',
                                                         url=confirmation_url))
                                payment_markup.add(
                                    InlineKeyboardButton(text='Договор оферты', url=f'{SITE_DOMAIN}/oferta/'))
                                payment_markup.add(
                                    InlineKeyboardButton(text='Политика ПДн', url=f'{SITE_DOMAIN}/policy/'))
                                payment_markup.add(
                                    InlineKeyboardButton(text='Пользовательское соглашение',
                                                         url=f'{SITE_DOMAIN}/user-agreement/'))
                                payment_markup.add(InlineKeyboardButton(text=f'🔙 Назад', callback_data=f'back'))
                                await edit_screen(
                                    call,
                                    f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                    reply_markup=payment_markup,
                                )
                                _schedule_payment_followup(call, user)
                            except Exception as e:
                                await edit_screen(
                                    call,
                                    f"Произошла ошибка при оформлении подписки.  Попробуйте позже. {e}",
                                    reply_markup=markup.start(user=user),
                                )

                        elif 'robokassa' in data:
                            # Создание платежа через RoboKassa (бот-магазин)
                            price = None
                            days = None
                            prices = Prices.objects.get(pk=1)

                            if data[-1] == '1':
                                price = prices.price_1
                                days = 31
                            elif data[-1] == '2':
                                price = prices.price_2
                                days = 93
                            elif data[-1] == '3':
                                price = prices.price_3
                                days = 186
                            elif data[-1] == '4':
                                price = prices.price_4
                                days = 366
                            elif data[-1] == '3_days_trial':
                                price = prices.price_5
                                days = 3

                            try:
                                amount_decimal = Decimal(str(price))

                                # 1) Создаём pending-транзакцию (InvId = id; рекуррент и триал — с Recurring=true по оферте)
                                transaction = Transaction.objects.create(
                                    status='pending',
                                    paid=False,
                                    amount=amount_decimal,
                                    user=user,
                                    currency='RUB',
                                    income_info=IncomeInfo.objects.get(pk=1),
                                    side='Приход средств',
                                    description=f'Приобретение подписки (RoboKassa BOT, {days} дн.)',
                                    payment_system='RoboKassaBot',
                                    robokassa_is_recurring_parent=True,
                                )
                                transaction.robokassa_invoice_id = str(transaction.id)
                                transaction.robokassa_recurring_previous_inv_id = str(transaction.id)
                                transaction.save(update_fields=['robokassa_invoice_id'])

                                inv_id = transaction.id  # InvId для RobokassaBotResultView

                                # 2) Формируем ссылку RoboKassa для бота

                                # Формируем Receipt
                                receipt = {
                                    "sno": "usn_income",  # или "osn", зависит от вашей СНО
                                    "items": [
                                        {
                                            "name": f"Подписка DomVPN на {days} дн.",
                                            "quantity": 1,
                                            "sum": int(amount_decimal),  # в копейках
                                            "payment_method": "full_payment",
                                            "payment_object": "service",
                                            "tax": "vat0"
                                        }
                                    ]
                                }

                                # URL-кодируем Receipt перед включением в подпись
                                receipt_url_encoded = quote(json.dumps(receipt, separators=(',', ':')), safe='')

                                merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_BOT
                                password_1 = settings.ROBOKASSA_PASSWORD_1_BOT
                                base_url = getattr(
                                    settings,
                                    'ROBOKASSA_BOT_ENDPOINT',
                                    'https://auth.robokassa.ru/Merchant/Index.aspx',
                                )

                                out_sum_str = f"{amount_decimal:.2f}"

                                # signature = robokassa_md5(
                                #     f"{merchant_login}:{out_sum_str}:{inv_id}:{password_1}"
                                # )

                                # Подпись теперь включает Receipt
                                signature = robokassa_md5(
                                    f"{merchant_login}:{out_sum_str}:{inv_id}:{receipt_url_encoded}:{password_1}"
                                )

                                success_url = f"https://t.me/{BOT_USERNAME}?start"
                                fail_url = f"https://t.me/{BOT_USERNAME}?start"

                                # params = {
                                #     'MerchantLogin': merchant_login,
                                #     'OutSum': out_sum_str,
                                #     'InvId': str(inv_id),
                                #     'Description': f'Подписка DomVPN на {days} дн.',
                                #     'SignatureValue': signature,
                                #     'SuccessURL': success_url,
                                #     'FailURL': fail_url,
                                #     'Recurring': 'true',
                                # }

                                params = {
                                    'MerchantLogin': merchant_login,
                                    'OutSum': out_sum_str,
                                    'InvId': str(inv_id),
                                    'Description': f'Подписка DomVPN на {days} дн.',
                                    'SignatureValue': signature,
                                    'SuccessURL': success_url,
                                    'FailURL': fail_url,
                                    'Recurring': 'true',
                                    'Receipt': receipt_url_encoded,  # ← добавлено
                                }

                                redirect_url = f"{base_url}?{urlencode(params)}"

                                Logging.objects.create(
                                    category="payment",
                                    log_level="INFO",
                                    message=f'[BOT-ROBO] [Платёжный запрос на сумму {out_sum_str} р.]',
                                    datetime=datetime.now(),
                                    user=user,
                                )

                                # 3) Отправляем пользователю кнопку с ссылкой на оплату
                                payment_markup = InlineKeyboardMarkup()
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text=f'💳 Оплатить подписку {str(days)} дн. за {str(price)}р.',
                                        url=redirect_url
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Договор оферты',
                                        url=f'{SITE_DOMAIN}/oferta/'
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Политика ПДн',
                                        url=f'{SITE_DOMAIN}/policy/'
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Пользовательское соглашение',
                                        url=f'{SITE_DOMAIN}/user-agreement/'
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(text='🔙 Назад', callback_data='back')
                                )

                                await edit_screen(
                                    call,
                                    f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                    reply_markup=payment_markup,
                                )
                                _schedule_payment_followup(call, user)

                            except Exception as e:
                                await edit_screen(
                                    call,
                                    f"Произошла ошибка при оформлении подписки через RoboKassa. Попробуйте позже. {e}",
                                    reply_markup=markup.start(user=user),
                                )

                        elif 'cryptobot' in data:
                            # Создание платежа через CryptoBot (бот-магазин)
                            price = None
                            days = None
                            prices = Prices.objects.get(pk=1)

                            if data[-1] == '1':
                                price = prices.price_1
                                days = 31
                            elif data[-1] == '2':
                                price = prices.price_2
                                days = 93
                            elif data[-1] == '3':
                                price = prices.price_3
                                days = 184
                            elif data[-1] == '4':
                                price = prices.price_4
                                days = 366
                            elif data[-1] == '3_days_trial':
                                price = prices.price_5
                                days = 3

                            try:
                                amount_decimal = Decimal(str(price))

                                # 1) Создаём pending-транзакцию
                                transaction = Transaction.objects.create(
                                    status='pending',
                                    paid=False,
                                    amount=amount_decimal,
                                    user=user,
                                    currency=getattr(settings, "CRYPTOBOT_ASSET_BOT", "USDT"),
                                    income_info=IncomeInfo.objects.get(pk=1),
                                    side='Приход средств',
                                    description=f'Приобретение подписки (CryptoBot BOT, {days} дн.)',
                                )

                                # 2) Создаём инвойс в CryptoBot
                                invoice = create_cryptobot_invoice_bot(
                                    amount=amount_decimal,
                                    days=days,
                                    transaction_id=transaction.id,
                                )
                                pay_url = invoice["pay_url"]
                                invoice_id = invoice.get("invoice_id")

                                if invoice_id is not None:
                                    transaction.payment_id = str(invoice_id)
                                    transaction.save()

                                Logging.objects.create(
                                    category="payment",
                                    log_level="INFO",
                                    message=f'[BOT-CRYPTO] [Платёжный запрос на сумму {amount_decimal} {getattr(settings, "CRYPTOBOT_ASSET_BOT", "USDT")}]',
                                    datetime=datetime.now(),
                                    user=user,
                                )

                                # 3) Отправляем кнопку с оплатой
                                payment_markup = InlineKeyboardMarkup()
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text=f'💳 Оплатить подписку {str(days)} дн. за {str(price)}',
                                        url=pay_url,
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Договор оферты',
                                        url=f'{SITE_DOMAIN}/oferta/',
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Политика ПДн',
                                        url=f'{SITE_DOMAIN}/policy/',
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(
                                        text='Пользовательское соглашение',
                                        url=f'{SITE_DOMAIN}/user-agreement/',
                                    )
                                )
                                payment_markup.add(
                                    InlineKeyboardButton(text='🔙 Назад', callback_data='back')
                                )

                                await edit_screen(
                                    call,
                                    f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                    reply_markup=payment_markup,
                                )
                                _schedule_payment_followup(call, user)

                            except Exception as e:
                                await edit_screen(
                                    call,
                                    f"Произошла ошибка при оформлении подписки через CryptoBot. Попробуйте позже. {e}",
                                    reply_markup=markup.start(user=user),
                                )

                    elif 'cancel_subscription' in data:
                        if user.subscription_status:
                            await edit_screen(
                                call,
                                msg.cancel_subscription,
                                reply_markup=markup.cancel_subscription(),
                            )
                        else:
                            await edit_screen(
                                call,
                                msg.cancel_subscription_error,
                                reply_markup=markup.start(user=user),
                            )


                    elif 'cancelled_sbs' in data:
                        Logging.objects.create(category="payment",
                                               log_level="INFO",
                                               message=f'[BOT] [ДЕЙСТВИЕ: ОТМЕНА ПОДПИСКИ ID Платежа: {user.payment_method_id}]',
                                               datetime=datetime.now(), user=user)
                        user.payment_method_id = None
                        user.robokassa_recurring_parent_inv_id = ''
                        user.permission_revoked = True
                        user.save()
                        revoke_all_user_keys(user, reason="manual_cancel_bot")
                        await edit_screen(
                            call,
                            msg.cancel_subscription_success,
                            reply_markup=markup.start(user=user),
                        )

                    elif 'site_access' in data:
                        lg.objects.create(log_level='INFO', message=f'[BOT] [site_access 2nd]', datetime=datetime.now(),
                                          user=user)

                        try:

                            tg_user = TelegramUser.objects.get(user_id=call.message.chat.id)
                            lg.objects.create(log_level='INFO', message=f'[BOT] [{tg_user}]', datetime=datetime.now(),
                                              user=user)

                            django_user = _ensure_site_user_for_telegram_user(tg_user)
                            lg.objects.create(log_level='INFO', message=f'[BOT] [{django_user}]',
                                              datetime=datetime.now(), user=user)

                            profile = tg_user.user_profile
                            lg.objects.create(log_level='INFO', message=f'[BOT] [{profile}]', datetime=datetime.now(),
                                              user=user)

                            site_domain = settings.DOMAIN
                            proxy_domain = settings.PROXY_DOMAIN
                            login_url = f"{proxy_domain}"

                            if not profile.site_password_generated:
                                password = _generate_and_set_site_password(django_user)
                                profile.site_password_generated = True
                                profile.save(update_fields=['site_password_generated'])

                                text = (
                                    "Ваши данные для входа на сайт DomVPN:\n\n"
                                    f"Логин: <code>{django_user.username}</code>\n"
                                    f"Пароль: <code>{password}</code>\n\n"
                                    f"Сайт: {login_url}\n\n"
                                    "Рекомендуем сразу изменить пароль в личном кабинете после первого входа."
                                )
                            else:
                                text = (
                                    "Ваш логин для входа на сайт DomVPN:\n\n"
                                    f"Логин: <code>{django_user.username}</code>\n\n"
                                    f"Сайт: {login_url}\n\n"
                                    "Пароль уже был выдан ранее.\n"
                                    "Если вы его забыли - нажмите кнопку «Изменить пароль на сайте», "
                                    "и мы сгенерируем новый."
                                )

                            await bot.send_message(
                                chat_id=call.message.chat.id,
                                text=format_screen(text, trail_for_callback(call.data, data)),
                                parse_mode='HTML',
                                reply_markup=markup.credentials_back(),
                            )
                        except Exception as e:
                            lg.objects.create(log_level='FATAL', message=f'[BOT] [{e}]', datetime=datetime.now(),
                                              user=user)

                    elif 'site_change_password' in data:
                        tg_user = TelegramUser.objects.get(user_id=call.message.chat.id)
                        django_user = _ensure_site_user_for_telegram_user(tg_user)
                        profile = tg_user.user_profile

                        site_domain = settings.DOMAIN
                        proxy_domain = settings.PROXY_DOMAIN

                        # login_url = f"{site_domain}/auth/accounts/login/"
                        login_url = f"{proxy_domain}"

                        password = _generate_and_set_site_password(django_user)
                        if profile and not profile.site_password_generated:
                            profile.site_password_generated = True
                            profile.save(update_fields=['site_password_generated'])

                        text = (
                            "Новый пароль для входа на сайт DomVPN:\n\n"
                            f"Логин: <code>{django_user.username}</code>\n"
                            f"Новый пароль: <code>{password}</code>\n\n"
                            f"Сайт: {login_url}\n\n"
                            "Старый пароль больше не действует."
                        )

                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=format_screen(text, trail_for_callback(call.data, data)),
                            parse_mode='HTML',
                            reply_markup=markup.credentials_back(),
                        )

                elif 'profile' in data:
                    user_id = user.user_id
                    income = user.income
                    sub = str(user.subscription_expiration.strftime(
                        "%d.%m.%Y")) if user.subscription_status else 'Нет подписки'
                    active = '📌  <b>Подписка:</b> ✅' if user.payment_method_id else ''

                    await edit_screen(
                        call,
                        msg.profile.format(user_id, sub, active, income),
                        reply_markup=markup.my_profile(user=user),
                    )

                elif 'tgproxy' in data:
                    if not can_use_mtproxy(user):
                        await edit_screen(
                            call,
                            'Раздел недоступен.',
                            reply_markup=markup.start(user=user),
                        )
                    else:
                        if 'reissue' in data:
                            key = reissue_key(user)
                            status_text = 'Ключ перевыпущен.' if key else 'Нет доступных прокси-нод.'
                        else:
                            key, created = issue_or_get_key(user)
                            if key and created:
                                status_text = 'Новый ключ создан.'
                            elif key:
                                status_text = 'У вас уже есть активный ключ.'
                            else:
                                status_text = 'Нет доступных прокси-нод.'

                        if key:
                            proxy_markup = InlineKeyboardMarkup()
                            proxy_markup.add(
                                InlineKeyboardButton(text='🔁 Перевыдать ключ', callback_data='tgproxy:reissue')
                            )
                            proxy_markup.add(InlineKeyboardButton(text='🔙 Назад', callback_data='back'))
                            await edit_screen(
                                call,
                                (
                                    f"🛰 MTProto Proxy\n\n"
                                    f"{status_text}\n\n"
                                    f"Ссылка для Telegram:\n<code>{key.tg_proxy_link}</code>\n\n"
                                    f"Web-ссылка:\n{key.web_proxy_link}"
                                ),
                                reply_markup=proxy_markup,
                            )
                        else:
                            await edit_screen(
                                call,
                                status_text,
                                reply_markup=markup.start(user=user),
                            )



                elif 'referral' in data:
                    bot_username = TelegramBot.objects.get(pk=1).username
                    user_income = TelegramUser.objects.get(user_id=call.message.chat.id).income
                    referral_code = call.message.chat.id
                    inv_1_lvl = TelegramReferral.objects.filter(referrer=user, level=1).__len__()
                    inv_2_lvl = TelegramReferral.objects.filter(referrer=user, level=2).__len__()
                    inv_3_lvl = TelegramReferral.objects.filter(referrer=user, level=3).__len__()
                    inv_4_lvl = TelegramReferral.objects.filter(referrer=user, level=4).__len__()
                    inv_5_lvl = TelegramReferral.objects.filter(referrer=user, level=5).__len__()
                    if not user.special_offer:
                        per_1 = ReferralSettings.objects.get(pk=1).level_1_percentage
                        per_2 = ReferralSettings.objects.get(pk=1).level_2_percentage
                        per_3 = ReferralSettings.objects.get(pk=1).level_3_percentage
                        per_4 = ReferralSettings.objects.get(pk=1).level_4_percentage
                        per_5 = ReferralSettings.objects.get(pk=1).level_5_percentage
                    else:
                        per_1 = user.special_offer.level_1_percentage
                        per_2 = user.special_offer.level_2_percentage
                        per_3 = user.special_offer.level_3_percentage
                        per_4 = user.special_offer.level_4_percentage
                        per_5 = user.special_offer.level_5_percentage
                    referral_link = f"Твоя реферальная ссылка: <code>https://t.me/{bot_username}?start={referral_code}</code>\n"
                    await edit_screen(
                        call,
                        referral_link + msg.referral.format(
                            inv_1_lvl, inv_2_lvl, inv_3_lvl, inv_4_lvl, inv_5_lvl, user_income,
                            per_1, per_2, per_3, per_4, per_5,
                        ),
                        reply_markup=markup.withdraw_funds(call.message.chat.id),
                    )

                elif 'withdraw' in data:

                    if user.income < 500:
                        await edit_screen(
                            call,
                            msg.withdraw_request_not_enough.format(user.income),
                            reply_markup=markup.proceed_to_profile(),
                        )
                        return

                    today = timezone.now().date()
                    has_requested_today = WithdrawalRequest.objects.filter(
                        user=user,
                        timestamp__date=today
                    ).exists()

                    if has_requested_today:
                        await edit_screen(
                            call,
                            msg.withdraw_request_duplicate.format(user.income),
                            reply_markup=markup.proceed_to_profile(),
                        )
                        return

                    try:
                        request = WithdrawalRequest.objects.create(
                                user=user,
                                amount=user.income,
                                currency='RUB',
                                timestamp=datetime.now()
                            )

                        await edit_screen(
                            call,
                            msg.withdraw_request.format(user.income),
                            reply_markup=markup.proceed_to_profile(),
                        )

                        admin_text = (f"💰 Запрос на вывод!\nПользователь: {user.get_full_name()}\nСумма: {user.income} RUB\n"
                                      f"<a>{settings.CSRF_TRUSTED_ORIGINS[0]}/admindomvpnx/bot/withdrawalrequest/{str(request.id)}/change/</a>")
                        for admin_id in [7516224613]:
                            try:
                                await bot.send_message(admin_id, text=admin_text)
                            except Exception as e:
                                lg.objects.create(log_level='INFO', message=f'[BOT] [Ошибка отправки админу {admin_id}: {e}]',
                                                  datetime=datetime.now(), user=user)

                    except Exception as e:
                        lg.objects.create(log_level='INFO', message=f'[BOT] [Ошибка при создании заявки: {e}]',
                                          datetime=datetime.now(),user=user)
                        await edit_screen(call, "Произошла ошибка. Попробуйте позже.")

                elif 'help' in data:
                    await edit_screen(call, msg.help_message, reply_markup=markup.start(user=user))

                elif 'common_info' in data:
                    await edit_screen(call, msg.commom_info, reply_markup=markup.help_markup())

                elif 'back' in data:
                    await edit_screen(call, msg.main_menu_choice, reply_markup=markup.start(user=user))
        except:
            ...

if __name__ == '__main__':
    bot.add_custom_filter(asyncio_filters.StateFilter(bot))
    loop = asyncio.get_event_loop()
    loop.create_task(send_pending_messages())  # MAILING
    loop.create_task(bot.polling(non_stop=True, request_timeout=100, timeout=100, skip_pending=True))  # TELEGRAM BOT
    loop.run_forever()
