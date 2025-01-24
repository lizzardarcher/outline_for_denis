from django.urls import path

from dashboard import views

urlpatterns = [
    path('profile/', views.ProfileView.as_view(), name='profile'),
]
