from django.urls import path

from apps.dashboard import views

urlpatterns = [
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('get_new_key/', views.CreateNewKeyView.as_view(), name='get_new_key'),
    path('update_key/<int:pk>', views.UpdateKeyView.as_view(), name='update_key'),
]
