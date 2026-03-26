import asyncio
import random
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import requests
from yookassa import Configuration, Payment

import django_orm
from django.conf import settings
from django.utils import timezone
from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from django.contrib.auth.models import User

from bot.models import TelegramBot, Prices, TelegramMessage, Logging, ReferralSettings
from bot.models import TelegramUser, UserProfile, TelegramReferral, VpnKey, Server, Country, IncomeInfo, \
    WithdrawalRequest, Transaction
from bot.models import Logging as lg

from bot.main.utils import msg
from bot.main.utils import markup

from bot.main.MarzbanAPI import MarzbanAPI

from bot.main.utils.utils import return_matches, robokassa_md5

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


async def send_pending_messages():
    while True:

        messages = TelegramMessage.objects.filter(status='not_sent')
        counter = 0
        for message in messages:

            users = []

            if message.send_to_subscribed:
                users += TelegramUser.objects.filter(subscription_status=True)
            elif message.send_to_notsubscribed:
                users += TelegramUser.objects.filter(subscription_status=False)
            else:
                users += TelegramUser.objects.all()

            for user in users:
                try:
                    await bot.send_message(chat_id=user.user_id, text=message.text, reply_markup=markup.for_sender())
                    counter += 1
                    message.counter = counter
                    message.save()
                    await asyncio.sleep(0.2)
                except Exception as e:
                    ...

            message.status = 'sent'
            message.counter = counter
            message.save()

        await asyncio.sleep(15)


def _ensure_site_user_for_telegram_user(tg_user: TelegramUser) -> User:
    """
    Гарантирует наличие Django-пользователя, связанного с TelegramUser через UserProfile.
    Возвращает объект User.
    """
    profile = getattr(tg_user, 'user_profile', None)
    if profile and profile.user:
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
    )
    UserProfile.objects.create(user=django_user, telegram_user=tg_user)
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
        login_url = f"{site_domain}/auth/accounts/login/"

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
    await bot.send_message(chat_id=message.chat.id,
                           text=msg.start_message.format(message.from_user.first_name,
                           prices['price_3_days'],
                           prices['price_1_month'],
                           prices['price_3_month'],
                           prices['price_6_month'],
                           prices['price_1_year'],),
                           reply_markup=markup.start())


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
                try:
                    await bot.delete_message(call.message.chat.id, call.message.message_id)
                except:
                    ...

                if 'download_app' in data:
                    await bot.send_message(call.message.chat.id, text=msg.download_app,
                                           reply_markup=markup.download_app())

                elif 'app_installed' in data:
                    await bot.send_message(chat_id=call.message.chat.id, text=msg.app_installed,
                                           reply_markup=markup.start())
                    # if user.subscription_status and not VpnKey.objects.filter(user=user):
                    #     server = random.choice(Server.objects.filter(is_active=True, keys_generated__lte=KEY_LIMIT))
                    #     key = await create_new_key(server, user)
                    #     await bot.send_message(chat_id=user.user_id, text=msg.trial_key.format(key))

                elif 'manage' in data:
                    await bot.send_message(call.message.chat.id, msg.choose_protocol,
                                           reply_markup=markup.choose_protocol())

                elif 'country' in data:

                    if 'outline' in data:

                        if user.subscription_status:
                            country = return_matches(country_list, data[-1])[0]
                            if country:
                                try:
                                    key = VpnKey.objects.filter(user=user, server__country__name=country).last()
                                    if key.protocol == 'outline':
                                        await bot.send_message(call.message.chat.id,
                                                               text=f'{msg.key_avail}\n<code>{key.access_url}</code>',
                                                               reply_markup=markup.key_menu(country, 'outline'))
                                    else:
                                        await bot.send_message(call.message.chat.id, text=msg.get_new_key,
                                                               reply_markup=markup.get_new_key(country, 'outline'))

                                except:
                                    await bot.send_message(call.message.chat.id, text=msg.get_new_key,
                                                           reply_markup=markup.get_new_key(country, 'outline'))
                        else:
                            await bot.send_message(call.message.chat.id, msg.no_subscription,
                                                   reply_markup=markup.get_subscription())

                    elif 'vless' in data:

                        if user.subscription_status:
                            country = return_matches(country_list, data[-1])[0]
                            if country:
                                try:
                                    key = VpnKey.objects.filter(user=user, server__country__name=country).last()
                                    if key.protocol == 'vless':
                                        await bot.send_message(call.message.chat.id,
                                                               text=f'{msg.key_avail}\n<code>{key.access_url}</code>',
                                                               reply_markup=markup.key_menu(country, 'vless'))
                                    else:
                                        await bot.send_message(call.message.chat.id, text=msg.get_new_key,
                                                               reply_markup=markup.get_new_key(country, 'vless'))
                                except:
                                    await bot.send_message(call.message.chat.id, text=msg.get_new_key,
                                                           reply_markup=markup.get_new_key(country, 'vless'))
                        else:
                            await bot.send_message(call.message.chat.id, msg.no_subscription,
                                                   reply_markup=markup.get_subscription())

                elif 'protocol_outline' in data:

                    await bot.send_message(call.message.chat.id, msg.avail_location_choice,
                                           reply_markup=markup.get_avail_location('outline'))

                elif 'protocol_vless' in data:

                    await bot.send_message(call.message.chat.id, msg.avail_location_choice,
                                           reply_markup=markup.get_avail_location('vless'))

                elif 'account' in data:

                    if 'get_new_key' in call.data or 'swap_key' in call.data:
                        protocol = call.data.split(':')[1]
                        if user.subscription_status:
                            try:
                                country = call.data.split('_')[-1]
                                server = Server.objects.filter(
                                    is_active=True,
                                    is_activated_vless=True,
                                    country__name=country,
                                    keys_generated__lte=200).order_by('keys_generated').first()

                                VpnKey.objects.filter(user=user).delete()  # Удаляем все предыдущие ключи
                                wait_msg = await bot.send_message(call.message.chat.id,
                                                                  text='Ожидайте, ключи генерируются...')
                                MarzbanAPI().delete_user(username=str(user.user_id))
                                await asyncio.sleep(2)
                                await bot.delete_message(wait_msg.chat.id, wait_msg.message_id)

                                MarzbanAPI().create_user(username=str(user.user_id))  # Генерируем новый ключ
                                success, result = MarzbanAPI().get_user(username=str(user.user_id))

                                links = result['links']
                                key = "---"
                                for link in links:

                                    if protocol == 'outline':
                                        if server.ip_address in link and "ss://" in link and not "vless://" in link:
                                            key = link
                                            break

                                    if protocol == 'vless':
                                        if server.ip_address in link and "vless://" in link:
                                            key = link
                                            break

                                key = VpnKey.objects.create(server=server, user=user, key_id=user.user_id,
                                                            name=str(user.user_id), password=str(user.user_id),
                                                            port=1040, method=protocol, access_url=key,
                                                            protocol=protocol)

                                await bot.send_message(call.message.chat.id,
                                                       text=f'{msg.key_avail}\n<code>{key.access_url}</code>',
                                                       reply_markup=markup.key_menu(country, protocol))
                            except:
                                ...
                        else:
                            await bot.send_message(call.message.chat.id, msg.no_subscription,
                                                   reply_markup=markup.get_subscription())

                    elif 'choose_payment' in data:
                        await bot.send_message(call.message.chat.id, text=msg.choose_subscription,
                                               reply_markup=markup.choose_subscription())
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
                        await bot.send_message(call.message.chat.id, text=msg.payment_menu.format(
                            sub, price, recurrent_price
                        ),
                                               reply_markup=markup.payment_menu(data[-1]))

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
                                Logging.objects.create(log_level="INFO",
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
                                await bot.send_message(call.message.chat.id,
                                                       f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                                       reply_markup=payment_markup)
                                await asyncio.sleep(10)
                                await bot.send_message(call.message.chat.id, text=msg.after_payment,
                                                       reply_markup=markup.proceed_to_profile())
                            except Exception as e:
                                await bot.send_message(call.message.chat.id,
                                                       f"Произошла ошибка при оформлении подписки.  Попробуйте позже. {e}")

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
                                transaction.save(update_fields=['robokassa_invoice_id'])

                                inv_id = transaction.id  # InvId для RobokassaBotResultView

                                # 2) Формируем ссылку RoboKassa для бота
                                merchant_login = settings.ROBOKASSA_MERCHANT_LOGIN_BOT
                                password_1 = settings.ROBOKASSA_PASSWORD_1_BOT
                                base_url = getattr(
                                    settings,
                                    'ROBOKASSA_BOT_ENDPOINT',
                                    'https://auth.robokassa.ru/Merchant/Index.aspx',
                                )
                                is_test = getattr(settings, 'ROBOKASSA_BOT_IS_TEST', False)

                                out_sum_str = f"{amount_decimal:.2f}"
                                signature = robokassa_md5(
                                    f"{merchant_login}:{out_sum_str}:{inv_id}:{password_1}"
                                )

                                # URL успеха/ошибки для пользователя — можно вернуть его в бота,
                                # но основная логика уже в ResultURL (RobokassaBotResultView),
                                # так что достаточно указать, например, ссылку на бота:
                                success_url = f"https://t.me/{BOT_USERNAME}?start"
                                fail_url = f"https://t.me/{BOT_USERNAME}?start"

                                params = {
                                    'MerchantLogin': merchant_login,
                                    'OutSum': out_sum_str,
                                    'InvId': str(inv_id),
                                    'Description': f'Подписка DomVPN на {days} дн.',
                                    'SignatureValue': signature,
                                    'SuccessURL': success_url,
                                    'FailURL': fail_url,
                                    'Recurring': 'true',
                                }
                                if is_test:
                                    params['IsTest'] = '1'

                                redirect_url = f"{base_url}?{urlencode(params)}"

                                Logging.objects.create(
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

                                await bot.send_message(
                                    call.message.chat.id,
                                    f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                    reply_markup=payment_markup
                                )
                                await asyncio.sleep(10)
                                await bot.send_message(
                                    call.message.chat.id,
                                    text=msg.after_payment,
                                    reply_markup=markup.proceed_to_profile()
                                )

                            except Exception as e:
                                await bot.send_message(
                                    call.message.chat.id,
                                    f"Произошла ошибка при оформлении подписки через RoboKassa. Попробуйте позже. {e}"
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

                                await bot.send_message(
                                    call.message.chat.id,
                                    f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                    reply_markup=payment_markup,
                                )
                                await asyncio.sleep(10)
                                await bot.send_message(
                                    call.message.chat.id,
                                    text=msg.after_payment,
                                    reply_markup=markup.proceed_to_profile(),
                                )

                            except Exception as e:
                                await bot.send_message(
                                    call.message.chat.id,
                                    f"Произошла ошибка при оформлении подписки через CryptoBot. Попробуйте позже. {e}",
                                )


                    elif 'cancel_subscription' in data:
                        # Отмена подписки
                        if user.subscription_status:
                            await bot.send_message(call.message.chat.id, text=msg.cancel_subscription,
                                                   reply_markup=markup.cancel_subscription())
                        else:
                            await bot.send_message(call.message.chat.id, text=msg.cancel_subscription_error,
                                                   reply_markup=markup.start())

                    elif 'cancelled_sbs' in data:
                        # Подтверждение отмены подписки
                        Logging.objects.create(log_level="INFO",
                                               message=f'[BOT] [ДЕЙСТВИЕ: ОТМЕНА ПОДПИСКИ ID Платежа: {user.payment_method_id}]',
                                               datetime=datetime.now(), user=user)
                        user.payment_method_id = None
                        user.robokassa_recurring_parent_inv_id = ''
                        user.permission_revoked = True
                        user.save()
                        await bot.send_message(call.message.chat.id, text=msg.cancel_subscription_success,
                                               reply_markup=markup.start())

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
                            login_url = f"{site_domain}/auth/accounts/login/"

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
                                    "Если вы его забыли — нажмите кнопку «Изменить пароль на сайте», "
                                    "и мы сгенерируем новый."
                                )

                            await bot.send_message(
                                chat_id=call.message.chat.id,
                                text=text,
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            lg.objects.create(log_level='FATAL', message=f'[BOT] [{e}]', datetime=datetime.now(),
                                              user=user)

                    elif 'site_change_password' in data:
                        tg_user = TelegramUser.objects.get(user_id=call.message.chat.id)
                        django_user = _ensure_site_user_for_telegram_user(tg_user)
                        profile = tg_user.user_profile

                        site_domain = settings.DOMAIN
                        login_url = f"{site_domain}/auth/accounts/login/"

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
                            text=text,
                            parse_mode='HTML'
                        )

                elif 'profile' in data:
                    user_id = user.user_id
                    income = user.income
                    sub = str(user.subscription_expiration.strftime(
                        "%d.%m.%Y")) if user.subscription_status else 'Нет подписки'
                    active = '📌  <b>Подписка:</b> ✅' if user.payment_method_id else ''

                    await bot.send_message(call.message.chat.id,
                                           text=msg.profile.format(user_id, sub, active, income),
                                           reply_markup=markup.my_profile(user=user))



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
                    await bot.send_message(call.message.chat.id,
                                           text=referral_link + msg.referral.format(
                                               inv_1_lvl, inv_2_lvl, inv_3_lvl, inv_4_lvl, inv_5_lvl, user_income,
                                                per_1, per_2, per_3, per_4, per_5),
                                           reply_markup=markup.withdraw_funds(call.message.chat.id))

                elif 'withdraw' in data:

                    # 1. Сначала проверяем минимальную сумму, чтобы не мучить базу лишними запросами
                    if user.income < 500:
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=msg.withdraw_request_not_enough.format(user.income),
                            reply_markup=markup.proceed_to_profile()
                        )
                        return  # Выходим из условия

                    # 2. Проверяем, был ли запрос сегодня (используем фильтр даты прямо в БД)
                    today = timezone.now().date()
                    has_requested_today = WithdrawalRequest.objects.filter(
                        user=user,
                        timestamp__date=today
                    ).exists()

                    if has_requested_today:
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=msg.withdraw_request_duplicate.format(user.income),
                            reply_markup=markup.proceed_to_profile()
                        )
                        return

                    # 3. Если проверки пройдены
                    try:
                        request = WithdrawalRequest.objects.create(
                                user=user,
                                amount=user.income,
                                currency='RUB',
                                timestamp=datetime.now()
                            )


                        # 4. Уведомляем пользователя
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=msg.withdraw_request.format(user.income),
                            reply_markup=markup.proceed_to_profile()
                        )

                        # 5. Уведомляем администраторов (через цикл)
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
                        await bot.send_message(call.message.chat.id, text="Произошла ошибка. Попробуйте позже.")

                elif 'help' in data:
                    await bot.send_message(call.message.chat.id, text=msg.help_message, reply_markup=markup.start(),
                                           parse_mode='HTML')

                elif 'popup_help' in data:
                    await bot.answer_callback_query(call.id, text=msg.popup_help, show_alert=True)

                elif 'common_info' in data:
                    await bot.send_message(call.message.chat.id, text=msg.commom_info,
                                           reply_markup=markup.help_markup())

                elif 'back' in data:
                    await bot.send_message(chat_id=call.message.chat.id, text=msg.main_menu_choice,
                                           reply_markup=markup.start())
        except:
            ...


if __name__ == '__main__':
    bot.add_custom_filter(asyncio_filters.StateFilter(bot))
    loop = asyncio.get_event_loop()
    loop.create_task(send_pending_messages())  # MAILING
    loop.create_task(bot.polling(non_stop=True, request_timeout=100, timeout=100, skip_pending=True))  # TELEGRAM BOT
    loop.run_forever()
