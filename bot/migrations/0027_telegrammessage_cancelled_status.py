from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0026_remove_server_api_url_remove_server_cert_sha256_and_more'),
    ]
    operations = [
        migrations.AlterField(
            model_name='telegrammessage',
            name='counter',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='Обработано пользователей',
            ),
        ),
        migrations.AlterField(
            model_name='telegrammessage',
            name='status',
            field=models.CharField(
                choices=[
                    ('sent', 'Отправлено'),
                    ('sending', 'Отправляется'),
                    ('cancelled', 'Отменено'),
                    ('not_sent', 'Не отправлено'),
                ],
                default='not_sent',
                max_length=20,
                verbose_name='Статус рассылки',
            ),
        ),
    ]
