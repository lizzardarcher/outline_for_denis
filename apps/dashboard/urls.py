from django.urls import path

from apps.dashboard import views



urlpatterns = [
    path('profile/', views.ProfileView.as_view(), name='profile'),
    # path('test_profile/', views.TestProfileView.as_view(), name='test_profile'),
    path('get_new_key/', views.CreateNewKeyView.as_view(), name='get_new_key'),
    path('update-subscription/<int:telegram_user_id>', views.UpdateSubscriptionView.as_view(),
         name='update_subscription'),
    path('cancel_subscription/<int:telegram_user_id>', views.CancelSubscriptionView.as_view(),
         name='cancel_subscription'),
    path('notifications/read/<int:notification_id>/', views.MarkNotificationReadView.as_view(),
         name='mark_notification_read'),
    path('mtproxy/manage/', views.ManageMtProxyView.as_view(), name='manage_mtproxy'),
    # path('analytics/', views.daily_transaction_analytics, name='daily_analytics'),
]
