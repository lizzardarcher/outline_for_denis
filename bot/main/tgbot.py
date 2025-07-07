import asyncio
import logging
import random
import sys
import traceback
from datetime import datetime, timedelta, date

from yookassa import Configuration, Payment

import django_orm
from django.conf import settings
from django.utils import timezone
from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage
from telebot.asyncio_handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.main.vless.MarzbanAPI import MarzbanAPI
from bot.models import TelegramBot, Prices, TelegramMessage, Logging
from bot.models import TelegramUser
from bot.models import TelegramReferral
from bot.models import VpnKey
from bot.models import Server
from bot.models import Country
from bot.models import IncomeInfo
from bot.models import WithdrawalRequest
from bot.models import Transaction
from bot.models import Logging as lg

from bot.main.utils import msg
from bot.main.utils import markup

from bot.main.utils.utils import return_matches
from bot.main.outline_client import create_new_key
from bot.main.outline_client import delete_user_keys

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s %(levelname) -8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y.%m.%d %I:%M:%S',
    handlers=[
        # TimedRotatingFileHandler(filename=log_path, when='D', interval=1, backupCount=5),
        logging.StreamHandler(stream=sys.stderr)
    ],
)

bot = AsyncTeleBot(token=TelegramBot.objects.all().first().token, state_storage=StateMemoryStorage())
bot.parse_mode = 'HTML'
DEBUG = settings.DEBUG
BOT_USERNAME = settings.BOT_USERNAME
KEY_LIMIT = settings.KEY_LIMIT

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


async def update_user_subscription_status():
    while True:
        users = TelegramUser.objects.filter(subscription_expiration__lt=timezone.now(), subscription_status=True)
        logger.info(f'[Всего просроченных пользователей] [{users.count()}] [Текущее время: {timezone.now()}]')
        for user in users:
            try:
                user.subscription_status = False
                user.save()
                try:
                    await bot.send_message(chat_id=user.user_id, text=msg.subscription_expired)
                except:
                    pass
                lg.objects.create(log_level='WARNING', message='[BOT] [Закончилась подписка у пользователя]',
                                  datetime=datetime.now(), user=user)
            except Exception as e:
                logger.error(f'[Ошибка при автообновлении статуса подписки {user} :\n{traceback.format_exc()}]')
                lg.objects.create(log_level='FATAL',
                                  message=f'[BOT] [Ошибка при автообновлении статуса подписки:\n{traceback.format_exc()}]',
                                  datetime=datetime.now())

        vpn_keys = VpnKey.objects.filter(user__subscription_status=False)
        for key in vpn_keys:
            if key.protocol == 'outline':
                try:
                    await delete_user_keys(user=key.user)
                except:
                    pass
            elif key.protocol == 'vless':
                try:
                    MarzbanAPI().delete_user(username=str(key.user.user_id))
                    key.delete()
                except:
                    pass

        await asyncio.sleep(60 * 60 * 12)


@bot.message_handler(commands=['start'])
async def start(message):
    """
    1. Создание нового пользователя
    2. Создание реферальной связи до 5 ур.
    """
    if message.chat.type == 'private':
        print(message.text)
        logger.info(
            f'[{message.from_user.first_name} : {message.from_user.username} : {message.from_user.id}] [msg: {message.text}]')
        try:
            TelegramUser.objects.create(user_id=message.from_user.id,
                                        username=message.from_user.username,
                                        first_name=message.from_user.first_name,
                                        last_name=message.from_user.last_name,
                                        subscription_status=False,
                                        subscription_expiration=datetime.now() - timedelta(days=1))
            # await bot.send_message(chat_id=message.chat.id, text=msg.new_user_bonus)
            lg.objects.create(log_level='INFO', message='[BOT] [Создан новый пользователь]', datetime=datetime.now(),
                              user=TelegramUser.objects.get(user_id=message.from_user.id))
            if message.text.split(' ')[-1].isdigit():
                referred_by = message.text.split(' ')[-1]
                same_user_check = str(referred_by) == str(message.chat.id)
                if not same_user_check:
                    try:
                        referrer = TelegramUser.objects.get(user_id=referred_by)  # тот, от кого получена ссылка
                        referred = TelegramUser.objects.get(user_id=message.chat.id)  # тот, кто воспользовался ссылкой
                        try:
                            TelegramReferral.objects.create(referrer=referrer, referred=referred, level=1)

                            #  Проверяем есть ли рефералы у того, кто отправил ссылку и получаем их список, если есть
                            referred_list = [x for x in TelegramReferral.objects.filter(referred=referrer, level__lte=4)]
                            for r in referred_list:
                                current_level = r.level  # 1
                                current_referrer = r.referrer
                                new_referral = TelegramReferral.objects.create(referrer=current_referrer, referred=referred,
                                                                               level=current_level + 1)
                                logger.info(f'Создана новая реферальная связь {new_referral}')
                                lg.objects.create(log_level='INFO',
                                                  message=f'[BOT] [Создана новая реферальная связь {new_referral}]',
                                                  datetime=datetime.now(),
                                                  user=TelegramUser.objects.get(user_id=message.from_user.id))
                        except:
                            logger.error(f'{traceback.format_exc()}')
                    except:
                        logger.error(f'{traceback.format_exc()}')
                        lg.objects.create(log_level='FATAL', message=f'[BOT] [ОШИБКА:\n{traceback.format_exc()}]',
                                          datetime=datetime.now(),
                                          user=TelegramUser.objects.get(user_id=message.from_user.id))

        except:
            ...
        await bot.send_message(chat_id=message.chat.id, text=msg.start_message.format(message.from_user.first_name),
                               reply_markup=markup.get_app_or_start())


@bot.message_handler(commands=['menu'])
async def menu(message):
    await bot.send_message(chat_id=message.chat.id, text=msg.start_message.format(message.from_user.first_name),
                           reply_markup=markup.start())


@bot.message_handler(commands=['payment'])
async def got_payment(message):
    """
    Обработка платежа
    """
    print(message)
    await bot.send_message(chat_id=message.chat.id, text='Success', reply_markup=markup.back())


### РАСЫЛКА ############################################################################################################
########################################################################################################################
class MyStates(StatesGroup):
    msg_text = State()  # statesgroup should contain states


@bot.message_handler(commands=['send'])
async def send_handler(message):
    if message.chat.type == 'private' and message.chat.id in [5566146968, ]:
        await bot.set_state(message.from_user.id, MyStates.msg_text, message.chat.id)
        await bot.reply_to(message, text='Введите сообщение, которое вы хотите отпавить '
                                         'всем пользователям бота:...')


@bot.message_handler(state="*", commands='cancel')
async def any_state(message):
    """
    Cancel state
    """
    await bot.send_message(message.chat.id, "Рассылка отменена")
    await bot.delete_state(message.from_user.id, message.chat.id)


@bot.message_handler(state=MyStates.msg_text)
async def get_text(message):
    async with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['msg_text'] = message.text
        user_ids = [x.user_id for x in TelegramUser.objects.all()]
        # user_ids = [5566146968, 211583618]
        count = 0
        text = data['msg_text']
        if message.content_type == 'text':
            for user_id in user_ids:
                try:
                    await bot.send_message(chat_id=user_id, text=text)
                    count += 1
                except:
                    print(traceback.format_exc())
        elif message.content_type == 'photo':

            for user_id in user_ids:
                try:
                    await bot.send_photo(chat_id=user_id, photo=message.photo[0].file_id, caption=text)
                    count += 1
                except:
                    print(traceback.format_exc())

        elif message.content_type == 'video':

            for user_id in user_ids:
                try:
                    await bot.send_video(chat_id=user_id, video=message.video[0].file_id, caption=text)
                    count += 1
                except:
                    print(traceback.format_exc())
    await bot.send_message(chat_id=message.chat.id,
                           text=f'Рассылка закончена. Сообщение:\n{text}\n отправлено {count} пользователям')

    await bot.delete_state(message.from_user.id, message.chat.id)


### КОНЕЦ РАСЫЛКИ ######################################################################################################
########################################################################################################################


@bot.message_handler(content_types=['text'])
async def handle_referral(message):
    """
    Обработка входящего значения при попытке пополнения баланса
    """
    if message.chat.type == 'private':
        logger.info(
            f'[{message.from_user.first_name} : {message.from_user.username} : {message.from_user.id}] [msg: {message.text}]')
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
                logger.error(f'{traceback.format_exc()}')
                lg.objects.create(log_level='FATAL',
                                  message=f'[BOT] [Ошибка при пополнении баланса:\n{traceback.format_exc()}]',
                                  datetime=datetime.now(), user=user)


@bot.message_handler(commands=['payment'])
async def got_payment(message):
    """
    Обработка платежа
    """
    await bot.send_message(chat_id=message.chat.id, text='Success', reply_markup=markup.back())




@bot.callback_query_handler(func=lambda call: True)
async def callback_query_handlers(call):
    try:
        data = call.data.split(':')
        print(
            f'[{call.message.chat.first_name}:{call.message.chat.username}:{call.message.chat.id}] [data: {call.data}]')
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

        async def send_dummy():
            await bot.send_message(call.message.chat.id, text=msg.dummy_message, reply_markup=markup.start())

        if call.message.chat.type == 'private':
            try:
                await bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                ...

            if 'download_app' in data:
                await bot.send_message(call.message.chat.id, text=msg.download_app, reply_markup=markup.download_app())

            elif 'app_installed' in data:
                await bot.send_message(chat_id=call.message.chat.id, text=msg.app_installed,
                                       reply_markup=markup.start())
                if user.subscription_status and not VpnKey.objects.filter(user=user):
                    server = random.choice(Server.objects.filter(is_active=True, keys_generated__lte=KEY_LIMIT))
                    logger.info(f"[app_installed] [SERVER] [{server}]")
                    key = await create_new_key(server, user)
                    await bot.send_message(chat_id=user.user_id, text=msg.trial_key.format(key))

            elif 'manage' in data:
                await bot.send_message(call.message.chat.id, msg.choose_protocol, reply_markup=markup.choose_protocol())

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
                                logger.error(f'[{user}] : {traceback.format_exc()}')
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
                                logger.error(f'[{user}] : {traceback.format_exc()}')
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

                if 'get_new_key' in call.data:
                    protocol = call.data.split(':')[1]
                    if user.subscription_status:
                        if protocol == 'outline':
                            try:
                                #  Удаляем все предыдущие ключи
                                await delete_user_keys(user=user)
                                country = call.data.split('_')[-1]
                                server = Server.objects.filter(
                                    is_active=True,
                                    is_activated=True,
                                    country__name=country,
                                    keys_generated__lte=KEY_LIMIT
                                ).order_by('keys_generated').first()
                                logger.info(f"[get_new_key] [SERVER] [{server}]")
                                key = await create_new_key(server=server, user=user)
                                await bot.send_message(call.message.chat.id,
                                                       text=f'{msg.key_avail}\n<code>{key}</code>',
                                                       reply_markup=markup.key_menu(country, protocol))
                            except:
                                logger.error(f'{traceback.format_exc()}')
                        elif protocol == 'vless':
                            try:
                                #  Удаляем все предыдущие ключи
                                _key = VpnKey.objects.filter(user=user)
                                _key.delete()

                                country = call.data.split('_')[-1]
                                server = Server.objects.filter(
                                    is_active=True,
                                    is_activated_vless=True,
                                    country__name=country,
                                    keys_generated__lte=KEY_LIMIT
                                ).order_by('keys_generated').first()
                                logger.info(f"[get_new_key] [SERVER] [{server}]")

                                MarzbanAPI().create_user(username=str(user.user_id))
                                success, result = MarzbanAPI().get_user(username=str(user.user_id))
                                links = result['links']
                                key = "---"
                                for link in links:
                                    if server.ip_address in link:
                                        key = link
                                        break
                                logger.info(f"VLESS_KEY: {key}")
                                key = VpnKey.objects.create(server=server, user=user, key_id=user.user_id,
                                                            name=str(user.user_id), password=str(user.user_id),
                                                            port=1040, method='vless', access_url=key, protocol='vless')

                                await bot.send_message(call.message.chat.id,
                                                       text=f'{msg.key_avail}\n<code>{key.access_url}</code>',
                                                       reply_markup=markup.key_menu(country, protocol))
                            except:
                                logger.error(f'{traceback.format_exc()}')
                    else:
                        await bot.send_message(call.message.chat.id, msg.no_subscription,
                                               reply_markup=markup.get_subscription())

                elif 'swap_key' in call.data:
                    protocol = call.data.split(':')[1]
                    if protocol == 'outline':
                        if user.subscription_status:
                            try:
                                #  Удаляем все предыдущие ключи
                                await delete_user_keys(user=user)
                                country = call.data.split('_')[-1]
                                server = Server.objects.filter(is_active=True, is_activated=True, country__name=country,
                                                               keys_generated__lte=KEY_LIMIT).last()
                                logger.info(f"[swap_key] [SERVER] [{server}]")
                                key = await create_new_key(server=server, user=user)
                                await bot.send_message(call.message.chat.id,
                                                       text=f'{msg.key_avail}\n<code>{key}</code>',
                                                       reply_markup=markup.key_menu(country, protocol))
                            except:
                                logger.error(f'{traceback.format_exc()}')
                        else:
                            await bot.send_message(call.message.chat.id, msg.no_subscription,
                                                   reply_markup=markup.get_subscription())
                    elif protocol == 'vless':
                        if user.subscription_status:

                            try:
                                #  Удаляем все предыдущие ключи
                                _key = VpnKey.objects.filter(user=user)
                                _key.delete()

                                country = call.data.split('_')[-1]

                                server = Server.objects.filter(is_active=True, is_activated_vless=True,
                                                               country__name=country, keys_generated__lte=KEY_LIMIT).last()

                                logger.info(f"[swap_key] [SERVER] [{server}]")

                                success, result = MarzbanAPI().get_user(username=str(user.user_id))

                                links = result['links']

                                key = "---"
                                for link in links:
                                    if server.ip_address in link:
                                        key = link
                                        break

                                logger.info(f"VLESS_KEY: {key}")

                                key = VpnKey.objects.create(server=server, user=user, key_id=user.user_id,
                                                            name=str(user.user_id), password=str(user.user_id),
                                                            port=1040, method='vless', access_url=key, protocol='vless')

                                await bot.send_message(call.message.chat.id,
                                                       text=f'{msg.key_avail}\n<code>{key.access_url}</code>',
                                                       reply_markup=markup.key_menu(country, protocol))
                            except:
                                logger.error(f'{traceback.format_exc()}')
                        else:
                            await bot.send_message(call.message.chat.id, msg.no_subscription,
                                                   reply_markup=markup.get_subscription())

                elif 'choose_payment' in data:
                    await bot.send_message(call.message.chat.id, text=msg.choose_subscription,
                                           reply_markup=markup.choose_subscription())
                elif 'sub' in data :
                    await bot.send_message(call.message.chat.id, text=msg.payment_menu,
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
                            price = 20
                            days = prices.price_5

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
                                }
                            }, )

                            Transaction.objects.create(status='pending', paid=False, amount=float(price), user=user,
                                                       currency='RUB', income_info=IncomeInfo.objects.get(pk=1),
                                                       side='Приход средств',
                                                       description='Пополнение баланса пользователя',
                                                       payment_id=payment.id)
                            Logging.objects.create(log_level="INFO",
                                                   message=f'[BOT] [Платёжный запрос на сумму {str(price)} р.]',
                                                   datetime=datetime.now(), user=user)

                            confirmation_url = payment.confirmation.confirmation_url
                            payment_markup = InlineKeyboardMarkup()
                            payment_markup.add(
                                InlineKeyboardButton(text=f'💳 Оплатить подписку {str(days)} дн. за {str(price)}р.',
                                                     url=confirmation_url))
                            payment_markup.add(
                                InlineKeyboardButton(text='Договор оферты', url='https://domvpn.store/oferta/'))
                            payment_markup.add(InlineKeyboardButton(text=f'🔙 Назад', callback_data=f'back'))
                            await bot.send_message(call.message.chat.id,
                                                   f"Для оплаты подписки на {days} дн. нажмите на кнопку Оплатить и следуйте инструкциям:",
                                                   reply_markup=payment_markup)
                            await asyncio.sleep(10)
                            await bot.send_message(call.message.chat.id, text=msg.after_payment,
                                                   reply_markup=markup.proceed_to_profile())
                        except Exception as e:
                            print(f"Ошибка при создании платежа: {traceback.format_exc()}")
                            await bot.send_message(call.message.chat.id,
                                                   f"Произошла ошибка при оформлении подписки.  Попробуйте позже. {e}")


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
                    user.save()
                    await bot.send_message(call.message.chat.id, text=msg.cancel_subscription_success,
                                           reply_markup=markup.start())

            elif 'profile' in data:
                user_id = user.user_id
                income = user.income
                sub = str(user.subscription_expiration.strftime("%d.%m.%Y")) if user.subscription_status else 'Нет подписки'
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
                referral_link = f"Твоя реферальная ссылка: <code>https://t.me/{bot_username}?start={referral_code}</code>\n"
                await bot.send_message(call.message.chat.id,
                                       text=referral_link + msg.referral.format(inv_1_lvl, inv_2_lvl, inv_3_lvl,
                                                                                inv_4_lvl,
                                                                                inv_5_lvl, user_income),
                                       reply_markup=markup.withdraw_funds(call.message.chat.id))

            elif 'withdraw' in data:

                try:
                    #  Проверка на количество запросов (можно 1 в сутки)
                    timestamp = WithdrawalRequest.objects.filter(user=user).last().timestamp
                    if timestamp.date() == date.today():
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=msg.withdraw_request_duplicate.format(str(user.income)),
                            reply_markup=markup.proceed_to_profile()
                        )
                except:
                    if user.income >= 500:
                        #  Создание объекта запроса
                        WithdrawalRequest.objects.create(
                            user=user,
                            amount=user.income,
                            currency='RUB',
                            timestamp=datetime.now(),
                        )
                        await bot.send_message(call.message.chat.id, text=msg.withdraw_request.format(str(user.income)),
                                               reply_markup=markup.proceed_to_profile())
                        logger.info(
                            f'[{call.message.chat.first_name} : {call.message.chat.username} : {call.message.chat.id}] [withdrawal request: {user} {user.income}]')
                    else:
                        await bot.send_message(call.message.chat.id,
                                               text=msg.withdraw_request_not_enough.format(str(user.income)),
                                               reply_markup=markup.proceed_to_profile())

            elif 'help' in data:
                await bot.send_message(call.message.chat.id, text=msg.help_message, reply_markup=markup.start(),
                                       parse_mode='HTML')

            elif 'popup_help' in data:
                await bot.answer_callback_query(call.id, text=msg.popup_help, show_alert=True)

            elif 'common_info' in data:
                await bot.send_message(call.message.chat.id, text=msg.commom_info, reply_markup=markup.help_markup())

            elif 'back' in data:
                await bot.send_message(chat_id=call.message.chat.id, text=msg.main_menu_choice,
                                       reply_markup=markup.start())
    except:
        print(traceback.format_exc())


if __name__ == '__main__':
    bot.add_custom_filter(asyncio_filters.StateFilter(bot))
    loop = asyncio.get_event_loop()
    loop.create_task(send_pending_messages())                                                          # MAILING
    loop.create_task(bot.polling(non_stop=True, request_timeout=100, timeout=100, skip_pending=True))  # TELEGRAM BOT
    loop.run_forever()
