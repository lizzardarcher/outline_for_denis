# your_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('create-payment/', views.CreatePaymentView.as_view(), name='create_payment'),
    path('payment-success/', views.PaymentSuccessView.as_view(), name='payment_success'),
    path('payment-failure/', views.PaymentFailureView.as_view(), name='payment_failure'),
    path('yookassa-webhook/', views.YookassaWebhookView.as_view(), name='yookassa_webhook'),
    path('test-create-payment/', views.TestCreatePaymentView.as_view(), name='test_create_payment'),
    path('test-payment-success/', views.TestPaymentSuccessView.as_view(), name='test_payment_success'),
    path('test-payment-failure/', views.TestPaymentFailureView.as_view(), name='test_payment_failure'),
    path('bot/yookassa-webhook/', views.YookassaTGBOTWebhookView.as_view(), name='yookassa_tgbot_webhook')
]
