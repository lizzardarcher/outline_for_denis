from django.urls import path

from .views import (
    AdminDashboardIndexView,
    KeysListView,
    LogsListView,
    ServerCreateView,
    ServerDeleteView,
    ServersListView,
    ServerDetailView,
    ServerInitActionView,
    ServerUpdateView,
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
    path("servers/create/", ServerCreateView.as_view(), name="server_create"),
    path("servers/<int:server_id>/", ServerDetailView.as_view(), name="server_detail"),
    path("servers/<int:server_id>/edit/", ServerUpdateView.as_view(), name="server_update"),
    path("servers/<int:server_id>/delete/", ServerDeleteView.as_view(), name="server_delete"),
    path("servers/<int:server_id>/init/", ServerInitActionView.as_view(), name="server_init"),
    path("keys/", KeysListView.as_view(), name="keys"),
]
