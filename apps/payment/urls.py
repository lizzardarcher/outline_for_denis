from django.urls import path
from .views import ukassa, robokassa, cryptobot, report

urlpatterns = [

    # YOOKASSA
    path('create-payment/', ukassa.CreatePaymentView.as_view(), name='create_payment'),
    path('payment-success/', ukassa.PaymentSuccessView.as_view(), name='payment_success'),
    path('payment-failure/', ukassa.PaymentFailureView.as_view(), name='payment_failure'),
    path('bot/yookassa-webhook/', ukassa.YookassaTGBOTWebhookView.as_view(), name='yookassa_tgbot_webhook'),    # Webhook bot
    path('site/yookassa-webhook/', ukassa.YookassaSiteWebhookView.as_view(), name='yookassa_site_webhook'),    # Webhook site

    # ROBOKASSA
    path('create-payment-robokassa/', robokassa.CreateRobokassaPaymentView.as_view(), name='create_payment_robokassa'),
    path('site/robokassa/result/', robokassa.RobokassaSiteResultView.as_view(), name='robokassa_result_site'),    # Webhook robokassa site
    path('bot/robokassa/result/', robokassa.RobokassaBotResultView.as_view(), name='robokassa_result_bot'),    # Webhook robokassa site
    path('site/robokassa/success/', robokassa.RobokassaSuccessView.as_view(), name='robokassa_success'),
    path('site/robokassa/fail/', robokassa.RobokassaFailView.as_view(), name='robokassa_fail'),

    # CRYPTOBOT
    path('create-payment-cryptobot/', cryptobot.CreateCryptoBotPaymentView.as_view(), name='create_payment_cryptobot'),
    path('site/cryptobot/webhook/', cryptobot.CryptoBotSiteWebhookView.as_view(), name='cryptobot_site_webhook'),
    path('bot/cryptobot/webhook/', cryptobot.CryptoBotBotWebhookView.as_view(), name='cryptobot_bot_webhook'),
    path('site/cryptobot/success/', cryptobot.CryptoBotSuccessView.as_view(), name='cryptobot_success'),
    path('site/cryptobot/fail/', cryptobot.CryptoBotFailView.as_view(), name='cryptobot_fail'),

    # RESULT EXCEL
    path('export/transactions/xlsx/', report.TransactionExcelExportView.as_view(), name='export_transactions_xlsx'),

]
