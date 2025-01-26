# your_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('create-payment/', views.CreatePaymentView.as_view(), name='create_payment'), # URL для создания платежа
    path('payment-success/', views.PaymentSuccessView.as_view(), name='payment_success'), # URL для успеха
    path('payment-failure/', views.PaymentFailureView.as_view(), name='payment_failure'), # URL для неудачи
    path('yookassa-webhook/', views.YookassaWebhookView.as_view(), name='yookassa_webhook'), # URL для вебхука
]
