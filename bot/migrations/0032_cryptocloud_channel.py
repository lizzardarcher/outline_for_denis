from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0031_cloudpayments_token_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramuser',
            name='cryptocloud_channel',
            field=models.CharField(
                blank=True,
                default='',
                help_text='bot или site — какой магазин использовать для рекуррентных инвойсов.',
                max_length=16,
                verbose_name='CryptoCloud канал',
            ),
        ),

        migrations.AlterField(
            model_name='transaction',
            name='payment_system',
            field=models.CharField(
                blank=True,
                choices=[
                    ('YooKassaBot', 'Юкасса Бот'),
                    ('YooKassaSite', 'Юкасса Сайт'),
                    ('RoboKassaBot', 'Робокасса Бот'),
                    ('RoboKassaSite', 'Робокасса Сайт'),
                    ('CryptoBotBot', 'Криптобот Бот'),
                    ('CryptoBotSite', 'Криптобот Сайт'),
                    ('CloudPaymentsBot', 'CloudPayments Бот'),
                    ('CloudPaymentsSite', 'CloudPayments Сайт'),
                    ('CryptoCloudBot', 'CryptoCloud Бот'),
                    ('CryptoCloudSite', 'CryptoCloud Сайт'),
                ],
                default='YooKassaBot',
                max_length=255,
                null=True,
                verbose_name='Платёжная система',
            ),
        ),
    ]
