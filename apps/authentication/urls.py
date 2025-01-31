from django.urls import path

from apps.authentication import views

urlpatterns = [
    path('telegram-login/', views.telegram_login, name='telegram_login'),
    path('register/', views.register_view, name='register'),
]
