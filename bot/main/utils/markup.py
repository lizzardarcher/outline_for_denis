from django.conf import settings
from telebot.types import InlineKeyboardMarkup
from telebot.types import InlineKeyboardButton
from telebot.types import LabeledPrice
from telebot.types import ShippingOption
import django_orm
from bot.models import Prices, Country, TelegramUser, Server

# from bot.models import *


btn_back = InlineKeyboardButton(text=f'🔙 Назад', callback_data=f'back')
DOMAIN = settings.DOMAIN

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
    btn5 = InlineKeyboardButton(text=f'✅ Попробовать 3 дня за ({Prices.objects.get(pk=1).price_5} р)', callback_data=f'account:sub:3_days_trial')
    btn6 = InlineKeyboardButton(text=f'💲 Приобрести подписку', callback_data=f'account:choose_payment')
    btn7 = InlineKeyboardButton(text=f'📲 Скачать приложение', callback_data=f'download_app')
    markup.row(btn1, btn2)
    markup.row(btn4, btn3)
    markup.row(btn5)
    markup.row(btn6)
    markup.row(btn7)
    return markup


def choose_protocol():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f'🚀 VLESS', callback_data=f'protocol_vless'))
    markup.add(InlineKeyboardButton(text=f'🔑 OUTLINE', callback_data=f'protocol_outline'))
    markup.add(btn_back)
    return markup


def download_app():
    markup = InlineKeyboardMarkup()
    markup.add( InlineKeyboardButton(text=f'📱 iPhone/iPad (Outline)', url=f'https://itunes.apple.com/app/outline-app/id1356177741'))
    markup.add(InlineKeyboardButton(text=f'📱 Android (Outline)', url=f'https://play.google.com/store/apps/details?id=org.outline.android.client'))
    markup.add(InlineKeyboardButton(text=f'📺 Android TV (Outline)', url=f'https://github.com/agolyud/VPN_Outline_TV/releases/'))
    markup.add(InlineKeyboardButton(text=f'💻 Windows (Outline)', url=f'https://github.com/Jigsaw-Code/outline-apps/releases/download/v1.10.1/Outline-Client.exe'))
    markup.add(InlineKeyboardButton(text=f'💻 MacOS (Outline)', url=f'https://apps.apple.com/ru/app/outline-secure-internet-access/id1356178125'))
    markup.add(InlineKeyboardButton(text=f'💻 Linux (Outline)', url=f'https://s3.amazonaws.com/outline-releases/client/linux/stable/Outline-Client.AppImage'))

    markup.add( InlineKeyboardButton(text=f'📱 iPhone/iPad (Vless)',  url=f'https://apps.apple.com/ru/app/v2box-v2ray-client/id6446814690'))
    markup.add(InlineKeyboardButton(text=f'📱 Android (Vless)',       url=f'https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box&hl=ru&pli=1'))
    markup.add(InlineKeyboardButton(text=f'📺 Android TV (Vless)',    url=f'https://play.google.com/store/apps/details?id=com.v2raytun.android&hl=ru&pli=1'))
    markup.add(InlineKeyboardButton(text=f'💻 Windows (Vless)',       url=f'https://github.com/InvisibleManVPN/InvisibleMan-XRayClient/releases'))
    markup.add(InlineKeyboardButton(text=f'💻 MacOS (Vless)',         url=f'https://apps.apple.com/pl/app/v2raytun/id6476628951'))
    markup.add(InlineKeyboardButton(text=f'💻 Linux (Vless)',         url=f'https://snapcraft.io/v4freedom'))

    markup.add(InlineKeyboardButton(text=f'Приложение установлено 👌', callback_data=f'app_installed'))
    markup.add(btn_back)
    return markup


def help_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text='Ссылки на скачивание', url='https://telegra.ph/VPN--Ssylki-na-skachivanie-10-15'))
    markup.add(InlineKeyboardButton(text='Условия использования', url='https://telegra.ph/Usloviya-polzovaniya-servisom-DOM-VPN-12-21'))
    markup.add(InlineKeyboardButton(text='Инструкция', url='https://telegra.ph/Instrukciya-DOM-VPN-12-21'))
    markup.add(InlineKeyboardButton(text='Договор оферты', url=f'{DOMAIN}/oferta/'))
    markup.add(InlineKeyboardButton(text='Политика конфиденциальности', url=f'{DOMAIN}/policy/'))
    markup.add(btn_back)
    return markup


def back():
    markup = InlineKeyboardMarkup()
    markup.add(btn_back)
    return markup


def for_sender():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'💡 Управление VPN', callback_data=f'manage')
    markup.add(btn1)
    return markup


def get_avail_location(protocol: str):
    markup = InlineKeyboardMarkup()
    # countries = Country.objects.filter(is_active=True)
    servers = Server.objects.filter(is_active=True)
    countries = set([x.country for x in servers])
    for country in countries:
        markup.add(InlineKeyboardButton(text=country.name_for_app, callback_data=f'country:{protocol}:{country.name}'))
    markup.add(btn_back)
    return markup


def get_subscription():
    markup = InlineKeyboardMarkup()
    btn2 = InlineKeyboardButton(text=f'💲 Приобрести подписку', callback_data=f'account:choose_payment')
    btn3 = InlineKeyboardButton(text=f'🆘 Помощь', callback_data=f'popup_help')
    markup.row(btn2)
    markup.row(btn3)
    markup.row(btn_back)
    return markup


def cancel_subscription():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'✅ Подтвердить отмену подписки', callback_data=f'account:cancelled_sbs')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def proceed_to_profile():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'👨 Профиль', callback_data=f'profile')
    markup.row(btn1)
    markup.row(btn_back)
    return markup


def my_profile(user: TelegramUser):
    markup = InlineKeyboardMarkup()
    btn2 = InlineKeyboardButton(text=f'💲 Купить подписку', callback_data=f'account:choose_payment')
    btn3 = InlineKeyboardButton(text=f'🤝 Реферальная программа', callback_data=f'referral')
    btn4 = InlineKeyboardButton(text=f'🛑 Отменить подписку', callback_data=f'account:cancel_subscription')
    btn5 = InlineKeyboardButton(text=f'Договор оферты', url=f'{DOMAIN}/oferta/')
    markup.row(btn2)
    markup.row(btn3)
    markup.row(btn4)
    markup.row(btn5)
    markup.row(btn_back)
    return markup



def payment_menu(payment_type: str):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            text='Юкасса (СБП, Банковская карта)',
            callback_data=f'account:payment:ukassa:{payment_type}'
        )
    )
    # markup.add(
    #     InlineKeyboardButton(
    #         text='Криптовалюта (USDT, TON)',
    #         callback_data=f'account:payment:cryptobot:{payment_type}'
    #     )
    # )
    # markup.add(
    #     InlineKeyboardButton(
    #         text='Робокасса (карта/СБП)',
    #         callback_data=f'account:payment:robokassa:{payment_type}'
    #     )
    # )
    markup.add(
        InlineKeyboardButton(
            text='Оплачивая подписку я соглашаюсь с договором офертой',
            url=f'{DOMAIN}/oferta/'
        )
    )
    markup.add(btn_back)
    return markup

def choose_subscription():
    markup = InlineKeyboardMarkup()
    price = Prices.objects.get(pk=1)
    markup.add(InlineKeyboardButton(text=f'🟢 3 дня ({price.price_5} р)', callback_data=f'account:sub:3_days_trial'))
    markup.add(InlineKeyboardButton(text=f'🟢 1 месяц ({price.price_1} р)', callback_data=f'account:sub:1'))
    markup.add(InlineKeyboardButton(text=f'🟢 3 месяца ({price.price_2} р)', callback_data=f'account:sub:2'))
    markup.add(InlineKeyboardButton(text=f'🟢 6 месяцев ({price.price_3} р)', callback_data=f'account:sub:3'))
    markup.add(InlineKeyboardButton(text=f'🟢 1 год ({price.price_4} р)', callback_data=f'account:sub:4'))

    markup.add(btn_back)
    return markup


def key_menu(country: str, protocol: str):
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'🔃 Заменить ключ', callback_data=f'account:{protocol}:swap_key_{country}')
    btn2 = InlineKeyboardButton(text=f'❔ Помощь', callback_data=f'help')
    markup.row(btn1, btn2)
    markup.row(btn_back)
    return markup


def get_new_key(country: str, protocol: str):
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton(text=f'🔑 Получить ключ', callback_data=f'account:{protocol}:get_new_key_{country}')
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
