from django.urls import path
from bot import views

urlpatterns = [
    path('dashboard/system_log/', views.SystemLogView.as_view(), name='system_log'),
]