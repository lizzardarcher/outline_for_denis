from django.urls import path

from apps.authentication import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('telegram-login/', views.telegram_login, name='telegram_login'),
    path('register/', views.register_view, name='register'),
    path('accounts/login/', views.UserLoginView.as_view(), name='login'),

    # path('accounts/profile/', views.ProfileView.as_view(), name='profile'),
    # path('accounts/profile/<int:pk>/', views.ProfileEditView.as_view(), name=f'profile_edit'),
    path('accounts/logout/', views.logout_view, name='logout'),
    # path('accounts/register/', views.RegisterView.as_view(), name='register'),
    path('accounts/password-change/', views.UserPasswordChangeView.as_view(), name='password_change'),
    # path('accounts/password-reset/', views.UserPasswordResetView.as_view(), name='password_reset'),

    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(
            template_name='account/password_reset.html',
            email_template_name='account/password_reset_email.html',
            subject_template_name='account/password_reset_subject.txt',
            success_url='/auth/accounts/password-reset-done/'
        ), name='password_reset'),


    path('accounts/password-reset-confirm/<uidb64>/<token>/', views.UserPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/password-reset-done/', auth_views.PasswordResetDoneView.as_view(template_name='account/password_reset_done.html'), name='password_reset_done'),
    path('accounts/password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='account/password_reset_complete.html'), name='password_reset_complete'),

]

