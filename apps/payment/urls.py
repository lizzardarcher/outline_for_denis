# your_app/urls.py
from django.urls import path
from .views import *

urlpatterns = [
    # path('create-payment/',   views_no_sub.CreatePaymentView.as_view(), name='create_payment'),
    # path('payment-success/',  views_no_sub.PaymentSuccessView.as_view(), name='payment_success'),
    # path('payment-failure/',  views_no_sub.PaymentFailureView.as_view(), name='payment_failure'),
    # path('yookassa-webhook/', views_no_sub.YookassaWebhookView.as_view(), name='yookassa_webhook'),

    path('create-payment/', CreatePaymentView.as_view(), name='create_payment'),
    path('payment-success/', PaymentSuccessView.as_view(), name='payment_success'),
    path('payment-failure/', PaymentFailureView.as_view(), name='payment_failure'),
    path('bot/yookassa-webhook/', YookassaTGBOTWebhookView.as_view(), name='yookassa_tgbot_webhook'),
    path('site/yookassa-webhook/', YookassaSiteWebhookView.as_view(), name='yookassa_site_webhook'),

    path('export/transactions/xlsx/', TransactionExcelExportView.as_view(), name='export_transactions_xlsx'),

    # path('yookassa-webhook/', views_no_sub.YookassaWebhookView.as_view(), name='yookassa_webhook'),

]
