import asyncio
import logging
import random
import traceback
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from math import ceil
from datetime import datetime, timedelta, date

import django_orm
from django.conf import settings
from django.utils import timezone
from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage
from telebot.asyncio_handler_backends import State, StatesGroup
from telebot.types import LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import TelegramBot, Prices, TelegramMessage
from bot.models import TelegramUser
from bot.models import TelegramReferral
from bot.models import VpnKey
from bot.models import Server
from bot.models import Country
from bot.models import IncomeInfo
from bot.models import ReferralSettings
from bot.models import WithdrawalRequest
from bot.models import Transaction
from bot.models import Logging as lg

from bot.main import msg
from bot.main import markup
from bot.main.utils import return_matches
from bot.main.outline_client import create_new_key
from bot.main.outline_client import delete_user_keys

log_path = Path(__file__).parent.absolute() / 'log/bot_log.log'
logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s %(levelname) -8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y.%m.%d %I:%M:%S',
    handlers=[
        TimedRotatingFileHandler(filename=log_path, when='D', interval=1, backupCount=5),
        # logging.StreamHandler(stream=sys.stderr)
    ],
)

bot = AsyncTeleBot(token=TelegramBot.objects.get(pk=1).token, state_storage=StateMemoryStorage())
bot.parse_mode = 'HTML'
DEBUG = settings.DEBUG


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
                    await bot.send_message(chat_id=user.user_id, text=message.text)
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
            try:
                await delete_user_keys(user=key.user)
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
                                        data_limit=5368709120 * 100,  # 5 GB at start
                                        subscription_status=True,
                                        subscription_expiration=datetime.now() + timedelta(days=3))
            await bot.send_message(chat_id=message.chat.id, text=msg.new_user_bonus)
            lg.objects.create(log_level='INFO', message='[BOT] [Создан новый пользователь]', datetime=datetime.now(),
                              user=TelegramUser.objects.get(user_id=message.from_user.id))
        except:
            ...
        await bot.send_message(chat_id=message.chat.id, text=msg.start_message.format(message.from_user.first_name),
                               reply_markup=markup.get_app_or_start())

        if message.text.split(' ')[-1].isdigit():
            referred_by = message.text.split(' ')[-1]
            same_user_check = str(referred_by) == str(message.chat.id)
            if not same_user_check:
                try:
                    referrer = TelegramUser.objects.get(user_id=referred_by)  # тот, от кого получена ссылка
                    referred = TelegramUser.objects.get(user_id=message.chat.id)  # тот, кто воспользовался ссылкой

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
                    lg.objects.create(log_level='FATAL', message=f'[BOT] [ОШИБКА:\n{traceback.format_exc()}]',
                                      datetime=datetime.now(),
                                      user=TelegramUser.objects.get(user_id=message.from_user.id))


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


@bot.pre_checkout_query_handler(func=lambda query: True)
async def checkout(pre_checkout_query):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message=msg.payment_unsuccessful)


@bot.message_handler(content_types=['successful_payment'])
async def got_payment(message):
    """
    Обработка платежа
    """
    payment = message.successful_payment
    logger.info(f'[{message.chat.first_name} : {message.chat.username} : {message.chat.id}] '
                f'[successful payment: {str(int(payment.total_amount) / 100)} {payment.currency} | {payment}]')

    user = TelegramUser.objects.get(user_id=message.chat.id)
    amount = float(message.successful_payment.total_amount / 100)

    lg.objects.create(log_level='SUCCESS', message=f'[BOT] [Пользователь успешно пополнил баланс на {str(amount)}P.]',
                      datetime=datetime.now(), user=user)

    currency = message.successful_payment.currency
    await bot.send_message(chat_id=message.chat.id, text=msg.payment_successful.format(amount, currency))
    await bot.send_message(chat_id=message.chat.id, text=msg.main_menu_choice, reply_markup=markup.start())
    balance = float(TelegramUser.objects.get(user_id=message.chat.id).balance) + amount
    TelegramUser.objects.filter(user_id=message.chat.id).update(balance=balance)

    income = float(IncomeInfo.objects.get(pk=1).total_amount)  # Общий доход проекта
    users_balance = float(IncomeInfo.objects.get(pk=1).user_balance_total)  # Общий баланс всех пользователей
    IncomeInfo.objects.all().update(total_amount=income + amount, user_balance_total=users_balance + amount)
    Transaction.objects.create(user=user, income_info=IncomeInfo.objects.get(pk=1), timestamp=datetime.now(),
                               currency=currency, amount=amount, side='Приход средств', paid=True, status='succeeded')

    referred_list = [x for x in TelegramReferral.objects.filter(referred=user)]
    if referred_list:
        for r in referred_list:
            user_to_pay = TelegramUser.objects.filter(user_id=r.referrer.user_id)[0]
            level = r.level
            percent = None
            if level == 1:
                percent = ReferralSettings.objects.get(pk=1).level_1_percentage
            elif level == 2:
                percent = ReferralSettings.objects.get(pk=1).level_2_percentage
            elif level == 3:
                percent = ReferralSettings.objects.get(pk=1).level_3_percentage
            elif level == 4:
                percent = ReferralSettings.objects.get(pk=1).level_4_percentage
            elif level == 5:
                percent = ReferralSettings.objects.get(pk=1).level_5_percentage
            if percent:
                income = float(TelegramUser.objects.get(user_id=user_to_pay.user_id).income) + (
                        amount * float(percent) / 100)
                TelegramUser.objects.filter(user_id=user_to_pay.user_id).update(income=income)
                await bot.send_message(user_to_pay.user_id,
                                       text=msg.income_from_referral.format(str(amount * float(percent) / 100)),
                                       reply_markup=markup.start())


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
                    server = random.choice(Server.objects.filter(is_active=True, keys_generated__lte=200))
                    logger.info(f"[app_installed] [SERVER] [{server}]")
                    key = await create_new_key(server, user)
                    await bot.send_message(chat_id=user.user_id, text=msg.trial_key.format(key))

            elif 'manage' in data:
                await bot.send_message(call.message.chat.id, msg.avail_location_choice,
                                       reply_markup=markup.get_avail_location())
            elif 'country' in data:
                if user.subscription_status:
                    keys = VpnKey.objects.filter(user=user)
                    country = return_matches(country_list, data)[0]

                    if country:
                        try:
                            key = VpnKey.objects.filter(user=user, server__country__name=country).last().access_url
                            await bot.send_message(call.message.chat.id, text=f'{msg.key_avail}\n<code>{key}</code>',
                                                   reply_markup=markup.key_menu(country))
                        except:
                            logger.error(f'[{user}] : {traceback.format_exc()}')
                            await bot.send_message(call.message.chat.id, text=msg.get_new_key,
                                                   reply_markup=markup.get_new_key(country))
                else:
                    await bot.send_message(call.message.chat.id, msg.no_subscription,
                                           reply_markup=markup.get_subscription())

            elif 'account' in data:

                if 'get_new_key' in call.data:
                    if user.subscription_status:
                        try:
                            #  Удаляем все предыдущие ключи
                            await delete_user_keys(user=user)
                            country = call.data.split('_')[-1]
                            server = Server.objects.filter(country__name=country, keys_generated__lte=200).last()
                            logger.info(f"[get_new_key] [SERVER] [{server}]")
                            key = await create_new_key(
                                server=server,
                                user=user)
                            await bot.send_message(call.message.chat.id, text=f'{msg.key_avail}\n<code>{key}</code>',
                                                   reply_markup=markup.key_menu(country))
                        except:
                            logger.error(f'{traceback.format_exc()}')
                    else:
                        await bot.send_message(call.message.chat.id, msg.no_subscription,
                                               reply_markup=markup.get_subscription())

                elif 'swap_key' in call.data:
                    if user.subscription_status:
                        try:
                            #  Удаляем все предыдущие ключи
                            await delete_user_keys(user=user)
                            country = call.data.split('_')[-1]
                            server = Server.objects.filter(country__name=country, keys_generated__lte=200).last()
                            logger.info(f"[swap_key] [SERVER] [{server}]")
                            key = await create_new_key(
                                server=server,
                                user=user)
                            await bot.send_message(call.message.chat.id, text=f'{msg.key_avail}\n<code>{key}</code>',
                                                   reply_markup=markup.key_menu(country))
                        except:
                            logger.error(f'{traceback.format_exc()}')
                    else:
                        await bot.send_message(call.message.chat.id, msg.no_subscription,
                                               reply_markup=markup.get_subscription())

                elif 'top_up_balance' in data:
                    await bot.send_message(call.message.chat.id, text=msg.paymemt_menu,
                                           reply_markup=markup.paymemt_menu())

                elif 'buy_subscripton' in data:
                    await bot.send_message(call.message.chat.id, text=msg.choose_subscription,
                                           reply_markup=markup.choose_subscription())

                elif 'payment' in data:
                    if 'ukassa' in data:
                        await bot.send_message(call.message.chat.id, text=msg.top_up_balance)
                        TelegramUser.objects.filter(user_id=user.user_id).update(top_up_balance_listener=True)
                    elif 'usdt' in data:
                        await bot.send_message(call.message.chat.id, text=msg.usdt_message,
                                               reply_markup=markup.proceed_to_profile())
                    elif 'details' in data:
                        keyboard = InlineKeyboardMarkup()
                        keyboard.add(InlineKeyboardButton("Оплатить", pay=True))
                        keyboard.add(InlineKeyboardButton(text=f'🔙 Назад', callback_data=f'back'))
                        price = LabeledPrice(label='Пополнение баланса', amount=int(data[-2]) * 100)
                        await bot.send_invoice(
                            chat_id=call.message.chat.id,
                            title='Outline VPN Key',
                            description='Пополнение баланса для генерации ключей Outline',
                            invoice_payload=f'{str(user.user_id)}:{data[-2]}',
                            provider_token=f'{payment_token}',
                            currency='RUB',
                            prices=[price],
                            photo_url='https://bitlaunch.io/blog/content/images/size/w2000/2022/10/Outline-VPN.png',
                            photo_height=512,  # !=0/None or picture won't be shown
                            photo_width=512,
                            photo_size=512,
                            provider_data='',
                            is_flexible=False,
                            need_phone_number=True,
                            send_phone_number_to_provider=True,
                            reply_markup=keyboard,
                        )

                elif 'sub' in data:
                    '''
                    1 мес - 359 ₽ 229 ₽
                    3 мес - 890 ₽ 649 ₽
                    6 мес - 1749 ₽ 1290 ₽
                    12 мес - 3190 ₽ 2290 ₽
                    '''
                    user_balance = user.balance
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

                    if user_balance < price:
                        await bot.send_message(call.message.chat.id, text=msg.low_balance,
                                               reply_markup=markup.top_up_balance())
                    else:
                        description = f' <code>{days}</code> за <code>{price}р.</code>'
                        await bot.send_message(call.message.chat.id, text=msg.confirm_subscription.format(description),
                                               reply_markup=markup.confirm_subscription(price=price, days=days))

                elif 'confirm_subscription' in data:
                    user_balance = user.balance
                    user_subscription_status = user.subscription_status
                    balance_after = user_balance - int(data[-2])
                    days = int(data[-1])

                    if user_subscription_status:
                        new_exp_date = user.subscription_expiration + timedelta(days=days)
                    else:
                        new_exp_date = datetime.now() + timedelta(days=days)

                    TelegramUser.objects.filter(user_id=user.user_id).update(
                        balance=balance_after, subscription_status=True,
                        subscription_expiration=new_exp_date)
                    try:
                        user_balance_total = IncomeInfo.objects.get(pk=1).user_balance_total - int(data[-2])
                        IncomeInfo.objects.filter(id=1).update(user_balance_total=user_balance_total)
                    except:
                        pass
                    await bot.send_message(call.message.chat.id, text=msg.sub_successful.format(new_exp_date, data[-2]),
                                           reply_markup=markup.proceed_to_profile())

            # todo  Разобраться с остатками ГБ

            elif 'profile' in data:
                # try:
                #     await update_keys_data_limit(user=user)
                # except:
                #     print(traceback.format_exc())
                user_id = user.user_id
                balance = user.balance
                income = user.income
                sub = str(user.subscription_expiration) if user.subscription_status else 'Нет подписки'
                reg_date = str(user.join_date)
                data_limit = str(ceil(user.data_limit / (1016 ** 3)))

                await bot.send_message(call.message.chat.id,
                                       text=msg.profile.format(user_id, balance, sub, reg_date, income),
                                       reply_markup=markup.my_profile())

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
    loop.create_task(update_user_subscription_status())                                                # SUBSCRIPTION REDEEM ON EXPIRATION
    loop.create_task(send_pending_messages())                                                          # MAILING
    loop.create_task(bot.polling(non_stop=True, request_timeout=100, timeout=100, skip_pending=True))  # TELEGRAM BOT
    loop.run_forever()
