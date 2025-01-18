import os
from datetime import datetime

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.template.defaultfilters import default


class AuthTelegramUser(AbstractUser):
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_username = models.CharField(max_length=255, blank=True)
    telegram_first_name = models.CharField(max_length=255, blank=True)
    telegram_last_name = models.CharField(max_length=255, blank=True)
    telegram_photo_url = models.URLField(blank=True)
    is_telegram_auth = models.BooleanField(default=False)

    def __str__(self):
        return self.username


class TelegramUser(models.Model):
    join_date = models.DateField(auto_now_add=True, verbose_name='Присоединился')
    user_id = models.BigIntegerField(unique=True, verbose_name='user_id')
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name='username')
    first_name = models.CharField(max_length=255, verbose_name='Имя')
    last_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='Фамилия')

    is_banned = models.BooleanField(default=False, verbose_name='Забанен')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00,
                                  verbose_name='Баланс для активации подписок')
    income = models.DecimalField(max_digits=10, decimal_places=2, default=0.00,
                                 verbose_name='Доход от реферальной программы')
    subscription_status = models.BooleanField(default=False, verbose_name='Статус подписки')
    subscription_expiration = models.DateField(default=None, blank=True, null=True,
                                               verbose_name='Дата окончания подписки')
    data_limit = models.BigIntegerField(verbose_name='Data Limit', blank=True, null=True, default=0)

    top_up_balance_listener = models.BooleanField(default=False, verbose_name='Top up balance listener')
    withdrawal_listener = models.BooleanField(default=False, verbose_name='Withdrawal listener')

    def __str__(self):
        if not self.last_name:
            last_name = ''
        else:
            last_name = self.last_name
        if not self.first_name:
            first_name = ''
        else:
            first_name = self.first_name
        if not self.username:
            username = ''
        else:
            username = '@' + self.username
        if not self.subscription_status:
            subscription_status = '❌'
        else:
            subscription_status = '✅'
        return f"{first_name} {last_name} {username} {subscription_status}"

    class Meta:
        verbose_name = 'Пользователь ТГ'
        verbose_name_plural = 'Пользователи ТГ'
        ordering = ['-join_date']


class TelegramReferral(models.Model):
    referrer = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='given_referrals',
                                 verbose_name='Поделился ссылкой')
    referred = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='received_referrals',
                                 verbose_name='Зарегистрирован по ссылке')
    level = models.IntegerField(default=0, verbose_name='Level')

    def __str__(self):
        return f"{self.referrer} {self.referrer}"

    class Meta:
        verbose_name = 'Реферал'
        verbose_name_plural = 'Рефералы'
        unique_together = ('referrer', 'referred')


class TelegramBot(models.Model):
    username = models.CharField(max_length=255, unique=True, verbose_name='Username')
    title = models.CharField(max_length=255, verbose_name='Название', blank=True, null=True)
    token = models.CharField(max_length=255, verbose_name='TG BOT Token', blank=True, null=True)
    created_at = models.DateField(auto_now_add=True, verbose_name='Создан')
    payment_system_api_key = models.CharField(default='', max_length=1000, blank=True, null=True, verbose_name='Payment system token')

    class Meta:
        verbose_name = 'Telegram Bot'
        verbose_name_plural = 'Telegram Bot'
        ordering = ['created_at']

    def __str__(self):
        return self.title


SIDE = (
    ('Приход средств', 'Приход средств'),
    ('Вывод средств', 'Вывод средств'),
)


class Transaction(models.Model):
    income_info = models.ForeignKey('IncomeInfo', on_delete=models.CASCADE, related_name='Доходы')
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, verbose_name='Пользователь')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Количество')
    currency = models.CharField(max_length=100, blank=True, null=True, verbose_name='Валюта')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='Время')
    side = models.CharField(max_length=100, blank=True, null=True, choices=SIDE, verbose_name='Направление транзакции')

    def __str__(self):
        return f"Транзакция пользователя - {self.user.username}: {self.amount} от {self.timestamp}"

    class Meta:
        verbose_name = 'Транзакция'
        verbose_name_plural = 'Транзакции'


class VpnKey(models.Model):
    created_at = models.DateField(auto_now_add=True, verbose_name='Создано')
    server = models.ForeignKey(to='Server', on_delete=models.CASCADE, verbose_name='Сервер', blank=True, null=True)
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, verbose_name='Пользователь')

    key_id = models.CharField(max_length=1000, verbose_name='Key ID', unique=True, primary_key=True)
    name = models.CharField(max_length=255, verbose_name='Name', blank=True, null=True)
    password = models.CharField(max_length=255, verbose_name='Password', blank=True, null=True)
    port = models.IntegerField(verbose_name='Port', blank=True, null=True)
    method = models.CharField(max_length=255, verbose_name='Method', blank=True, null=True)
    access_url = models.CharField(max_length=2000, verbose_name='Access URL', blank=True, null=True)
    used_bytes = models.BigIntegerField(verbose_name='Used Bytes', blank=True, null=True)
    data_limit = models.BigIntegerField(verbose_name='Data Limit', blank=True, null=True)

    def __str__(self):
        return f"{self.user} {self.access_url} ({self.created_at})"

    class Meta:
        verbose_name = 'VPN Ключ'
        verbose_name_plural = 'VPN Ключи'


class Server(models.Model):
    hosting = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Хостинг')
    ip_address = models.CharField(max_length=1000, blank=True, null=True, verbose_name='IP Address')
    user = models.CharField(max_length=1000, blank=True, null=True, default='root', verbose_name='Пользователь')
    password = models.CharField(max_length=1000, blank=True, null=True, default='<PASSWORD>', verbose_name='Пароль')
    # configuration = models.TextField(max_length=10000, blank=True, null=True, verbose_name='Конфигурация')
    rental_price = models.DecimalField(max_digits=10, blank=True, null=True, decimal_places=2, verbose_name='Цена аренды в месяц')
    max_keys = models.IntegerField(default=200, blank=True, null=True, verbose_name='Лимит ключей', editable=False)
    keys_generated = models.IntegerField(default=0, blank=True, null=True, verbose_name='Ключей сгенерировано')
    is_active = models.BooleanField(default=True, verbose_name='Сервер Активен')
    created_at = models.DateField(auto_now_add=True, verbose_name='Дата создания')
    api_url = models.CharField(max_length=1000, blank=True, null=True, verbose_name='API URL')
    cert_sha256 = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Certificate SHA256')
    script_out = models.JSONField(blank=True, null=True, verbose_name='Script Out Info JSON')
    country = models.ForeignKey('Country', on_delete=models.CASCADE, null=True, blank=True, verbose_name='Страна')

    is_activated = models.BooleanField(default=False, verbose_name='Сервер Активирован для Outline (не трогать)')

    def __str__(self):
        return f"{self.hosting} root@{self.ip_address} ({self.created_at}) {self.country.name}"

    class Meta:
        verbose_name = 'VPN сервер'
        verbose_name_plural = 'VPN сервера'


class Country(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True, verbose_name='Название страны')
    preset_id = models.IntegerField(null=True, blank=True, verbose_name='preset_id')
    is_active = models.BooleanField(default=True, null=True, blank=True, verbose_name='Активно')
    name_for_app = models.CharField(max_length=100, null=True, blank=True, default='', verbose_name='Name for app')

    def __str__(self):
        return f"{self.name_for_app}"

    class Meta:
        verbose_name = 'Страна'
        verbose_name_plural = 'Страны'


class GlobalSettings(models.Model):
    server_amount = models.IntegerField(blank=True, null=True, verbose_name='Количество сервероа')
    time_web_api_key = models.TextField(max_length=4000, blank=True, null=True, verbose_name='Time Web API Token')
    payment_system_api_key = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Ukassa token')
    # prices = models.ForeignKey(to='Price', on_delete=models.CASCADE, null=True, blank=True, verbose_name='Prices')
    cloud_init = models.TextField(max_length=4000, blank=True, null=True, verbose_name='Cloud Init')
    data_limit = models.BigIntegerField(blank=True, null=True, verbose_name='Data Limit GB')
    os_id = models.IntegerField(blank=True, null=True, verbose_name='OS id')
    software_id = models.IntegerField(blank=True, null=True, verbose_name='Software id')

    def __str__(self):
        return f"НАСТРОЙКИ: Количество VPN серверов: {str(self.server_amount)}"

    class Meta:
        verbose_name = 'Настройки'
        verbose_name_plural = 'Настройки'


class ReferralSettings(models.Model):
    level_1_percentage = models.IntegerField(blank=True, null=True, verbose_name='Level 1 Percentage')
    level_2_percentage = models.IntegerField(blank=True, null=True, verbose_name='Level 2 Percentage')
    level_3_percentage = models.IntegerField(blank=True, null=True, verbose_name='Level 3 Percentage')
    level_4_percentage = models.IntegerField(blank=True, null=True, verbose_name='Level 4 Percentage')
    level_5_percentage = models.IntegerField(blank=True, null=True, verbose_name='Level 5 Percentage')

    def __str__(self):
        return f"Level 1 ({self.level_1_percentage}%) --- Level 2: ({self.level_2_percentage}%) --- Level 3 ({self.level_3_percentage}%) --- Level 4 ({self.level_4_percentage}%) --- Level 5 ({self.level_5_percentage}%)"

    class Meta:
        verbose_name = 'Настройки Рефералов'
        verbose_name_plural = 'Настройки Рефералов'


class IncomeInfo(models.Model):
    total_amount = models.DecimalField(blank=True, null=True, decimal_places=2, max_digits=10,
                                       verbose_name='Общий баланс проекта')
    user_balance_total = models.DecimalField(blank=True, null=True, decimal_places=2, max_digits=10,
                                             verbose_name='Общий баланс всех пользователей')

    def __str__(self):
        return f'[Общий доход проекта: * {str(self.total_amount)} (RUB) *] [Общий баланс всех пользователей: * {str(self.user_balance_total)} (RUB) *]'

    class Meta:
        verbose_name = 'Доход'
        verbose_name_plural = 'Доходы'


class Price(models.Model):
    ru_1_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    ru_3_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    ru_6_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    ru_12_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)

    pol_1_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    pol_3_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    pol_6_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    pol_12_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)

    neth_1_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    neth_3_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    neth_6_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    neth_12_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)

    kaz_1_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    kaz_3_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    kaz_6_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
    kaz_12_month = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)

    def __str__(self):
        return 'Price'

    class Meta:
        verbose_name = 'Price'
        verbose_name_plural = 'Price'


class WithdrawalRequest(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, verbose_name='Пользователь')
    amount = models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2, verbose_name='Количество')
    status = models.BooleanField(default=False, verbose_name='Статус запроса о выводе средств')
    currency = models.CharField(blank=True, max_length=1000, verbose_name='Валюта')
    timestamp = models.DateTimeField(blank=True, null=True, verbose_name='Время')

    def __str__(self):
        return f'{self.user} - {self.amount.__str__()} {self.currency} {self.timestamp} - {self.status.__str__()}'

    def save(self, *args, **kwargs):
        if not self.status:
            super(WithdrawalRequest, self).save(*args, **kwargs)
        else:
            # При изменении статуса на True, вычитаем средства из дохода всех пользователей
            # Вычитаем доход из пользователя
            # Создаём объект транзакции на вывод средств
            user_balance_total = IncomeInfo.objects.get(pk=1).user_balance_total
            IncomeInfo.objects.filter(id=1).update(user_balance_total=user_balance_total - self.amount)
            income = TelegramUser.objects.get(user_id=self.user.user_id).income
            TelegramUser.objects.filter(user_id=self.user.user_id).update(income=income - self.amount)
            Transaction.objects.create(user=self.user, income_info=IncomeInfo.objects.get(pk=1),
                                       timestamp=datetime.now(), currency=self.currency, amount=self.amount,
                                       side='Вывод средств')
            super(WithdrawalRequest, self).save(*args, **kwargs)

    class Meta:
        verbose_name = 'Запрос на вывод средств'
        verbose_name_plural = 'Запросы на вывод средств'


LOG_LEVEL = (
    ('TRACE', 'TRACE'),
    ('DEBUG', 'DEBUG'),
    ('INFO', 'INFO'),
    ('WARNING', 'WARNING'),
    ('FATAL', 'FATAL'),
    ('SUCCESS', 'SUCCESS'),
)


class Logging(models.Model):
    log_level = models.CharField(max_length=50, null=True, blank=True, choices=LOG_LEVEL, verbose_name='LOG LEVEL')
    message = models.TextField(max_length=4000, null=True, blank=True, verbose_name='Сообщение')
    datetime = models.DateTimeField(auto_now_add=True, verbose_name='Время')
    user = models.ForeignKey(to='TelegramUser', null=True, blank=True, on_delete=models.SET_NULL,
                             verbose_name='Аккаунт')

    def __str__(self):
        return f'[{self.log_level}] {self.message} [{str(self.datetime)}] [{self.user}]'

    class Meta:
        verbose_name = 'Лог'
        verbose_name_plural = 'Логи'


class Prices(models.Model):
    price_1 = models.PositiveIntegerField(null=True, blank=True, verbose_name='price for 1 month')
    price_2 = models.PositiveIntegerField(null=True, blank=True, verbose_name='price for 3 month')
    price_3 = models.PositiveIntegerField(null=True, blank=True, verbose_name='price for 6 month')
    price_4 = models.PositiveIntegerField(null=True, blank=True, verbose_name='price for 12 month')

    def __str__(self):
        return f'{self.price_1} / {self.price_2} / {self.price_3} / {self.price_4}'

    class Meta:
        verbose_name = 'Цена'
        verbose_name_plural = 'Цены'