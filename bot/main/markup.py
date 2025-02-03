from telebot.types import InlineKeyboardMarkup
from telebot.types import InlineKeyboardButton
from telebot.types import LabeledPrice
from telebot.types import ShippingOption
import django_orm
from bot.models import Prices, Country

# from bot.models import *


btn_back = InlineKeyboardButton(text=f'🔙 Назад', callback_data=f'back')


def get_app_or_start():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f'📲 Скачать приложение', callback_data=f'download_app'))
    markup.add(InlineKeyboardButton(text=f'Приложение установлено 👌', callback_data=f'app_installed'))
    markup.add(btn_back)
    return markup


def start():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'💡 Управление VPN', callback_data=f'manage')
    btn2 = InlineKeyboardButton(text=f'👨 Профиль', callback_data=f'profile')
    btn3 = InlineKeyboardButton(text=f'🆘 Помощь', callback_data=f'help')
    btn4 = InlineKeyboardButton(text=f'ℹ Информация', callback_data=f'common_info')
    btn5 = InlineKeyboardButton(text=f'💳 Пополнить баланс', callback_data=f'account:top_up_balance')
    btn6 = InlineKeyboardButton(text=f'💲 Приобрести подписку', callback_data=f'account:buy_subscripton')
    btn7 = InlineKeyboardButton(text=f'📲 Скачать приложение', callback_data=f'download_app')
    markup.row(btn1, btn2)
    markup.row(btn4, btn3)
    markup.row(btn5, btn6)
    markup.row(btn7)
    return markup


def download_app():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(text=f'📱 iPhone/iPad', url=f'https://itunes.apple.com/app/outline-app/id1356177741'))
    markup.add(InlineKeyboardButton(text=f'📱 Android',
                                    url=f'https://play.google.com/store/apps/details?id=org.outline.android.client'))
    markup.add(InlineKeyboardButton(text=f'📺 Android TV',
                                    url=f'https://github.com/agolyud/VPN_Outline_TV/releases/'))
    markup.add(InlineKeyboardButton(text=f'💻 Windows',
                                    url=f'https://github.com/Jigsaw-Code/outline-apps/releases/download/v1.10.1/Outline-Client.exe'))
    markup.add(InlineKeyboardButton(text=f'💻 MacOS',
                                    url=f'https://apps.apple.com/ru/app/outline-secure-internet-access/id1356178125'))
    markup.add(InlineKeyboardButton(text=f'💻 Linux',
                                    url=f'https://s3.amazonaws.com/outline-releases/client/linux/stable/Outline-Client.AppImage'))
    markup.add(InlineKeyboardButton(text=f'Приложение установлено 👌', callback_data=f'app_installed'))
    markup.add(btn_back)
    return markup


def help_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text='Ссылки на скачивание',
                                    url='https://telegra.ph/VPN--Ssylki-na-skachivanie-11-20'))
    markup.add(InlineKeyboardButton(text='Условия использования',
                                    url='https://telegra.ph/Usloviya-polzovaniya-servisom-VPN-TON-11-20'))
    markup.add(InlineKeyboardButton(text='Инструкция', url='https://telegra.ph/Instrukciya-VPN-11-20'))
    markup.add(btn_back)
    return markup


def back():
    markup = InlineKeyboardMarkup()
    markup.add(btn_back)
    return markup


def get_avail_location():
    markup = InlineKeyboardMarkup()
    countries = Country.objects.filter(is_active=True)
    for country in countries:
        markup.add(InlineKeyboardButton(text=country.name_for_app, callback_data=f'country:{country.name}'))
    markup.add(btn_back)
    return markup


def get_subscription():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'💳 Пополнить баланс', callback_data=f'account:top_up_balance')
    btn2 = InlineKeyboardButton(text=f'💲 Приобрести подписку', callback_data=f'account:buy_subscripton')
    btn3 = InlineKeyboardButton(text=f'🆘 Помощь', callback_data=f'popup_help')
    markup.row(btn1, btn2)
    markup.row(btn3)
    markup.row(btn_back)
    return markup


def top_up_balance():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'💳 Пополнить баланс', callback_data=f'account:top_up_balance')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def confirm_subscription(price: int, days: int):
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'✅ Подтвердить приобретение подписки',
                                callback_data=f'account:confirm_subscription:{str(price)}:{str(days)}')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def proceed_to_profile():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'👨 Профиль', callback_data=f'profile')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def my_profile():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'💳 Пополнить баланс', callback_data=f'account:top_up_balance')
    btn2 = InlineKeyboardButton(text=f'💲 Купить подписку', callback_data=f'account:buy_subscripton')
    btn3 = InlineKeyboardButton(text=f'🤝 Реферальная программа', callback_data=f'referral')
    markup.row(btn1, btn2)
    markup.row(btn3)
    markup.row(btn_back)
    return markup


def paymemt_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f'Юкасса (Банковская карта)', callback_data=f'account:payment:ukassa'))
    markup.add(InlineKeyboardButton(text=f'Оплатить через сайт (Банковская карта, SberPay, ЮMoney)', url=f'https://domvpn.ru/auth/accounts/login/'))
    # markup.add(InlineKeyboardButton(text=f'USDT', callback_data=f'account:payment:usdt'))
    markup.add(btn_back)
    return markup


def choose_subscription():
    markup = InlineKeyboardMarkup()
    price = Prices.objects.get(pk=1)
    markup.add(InlineKeyboardButton(text=f'🟢 1 месяц ({price.price_1} р)', callback_data=f'account:sub:1'))
    markup.add(InlineKeyboardButton(text=f'🟢 3 месяца ({price.price_2} р)', callback_data=f'account:sub:2'))
    markup.add(InlineKeyboardButton(text=f'🟢 6 месяцев ({price.price_3} р)', callback_data=f'account:sub:3'))
    markup.add(InlineKeyboardButton(text=f'🟢 1 год ({price.price_4} р)', callback_data=f'account:sub:4'))
    # markup.add(InlineKeyboardButton(text=f'🟢 Пожизненная (2000 р)', callback_data=f'account:sub:5'))
    markup.add(btn_back)
    return markup


def key_menu(country: str):
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'🔃 Заменить ключ', callback_data=f'account:swap_key_{country}')
    btn2 = InlineKeyboardButton(text=f'❔ Помощь', callback_data=f'help')
    markup.row(btn1, btn2)
    markup.row(btn_back)
    return markup


def get_new_key(country: str):
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'🔑 Получить ключ', callback_data=f'account:get_new_key_{country}')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def payment_ukassa(price: int, chat_id: int):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(text="💳 Оплатить", callback_data=f'account:payment:details:{str(price)}:{str(chat_id)}'))
    markup.add(btn_back)
    return markup


def withdraw_funds(chat_id: int):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🤑 Вывести деньги", callback_data=f'withdraw:{str(chat_id)}'))
    markup.add(btn_back)
    return markup
