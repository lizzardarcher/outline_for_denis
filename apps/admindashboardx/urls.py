from django.urls import path

from .views import (
    AdminDashboardIndexView,
    KeysListView,
    LogsListView,
    ServersListView,
    ServerDetailView,
    TransactionDetailView,
    TransactionsListView,
    UserDetailView,
    UsersListView,
)

app_name = "admindashboardx"

urlpatterns = [
    path("", AdminDashboardIndexView.as_view(), name="index"),
    path("users/", UsersListView.as_view(), name="users"),
    path("users/<int:telegram_user_id>/", UserDetailView.as_view(), name="user_detail"),
    path("transactions/", TransactionsListView.as_view(), name="transactions"),
    path("transactions/<int:tx_id>/", TransactionDetailView.as_view(), name="transaction_detail"),
    path("logs/", LogsListView.as_view(), name="logs"),
    path("servers/", ServersListView.as_view(), name="servers"),
    path("servers/<int:server_id>/", ServerDetailView.as_view(), name="server_detail"),
    path("keys/", KeysListView.as_view(), name="keys"),
]
