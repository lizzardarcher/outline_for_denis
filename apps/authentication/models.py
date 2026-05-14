from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Пользователь сайта и админки (AUTH_USER_MODEL).
    PK — bigint (BigAutoField); Telegram id хранится только в bot.TelegramUser.user_id.
    """

    id = models.BigAutoField(primary_key=True)

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name="groups",
        blank=True,
        help_text="The groups this user belongs to. A user will get all permissions "
        "granted to each of their groups.",
        related_name="authentication_user_set",
        related_query_name="authentication_user",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="authentication_user_set",
        related_query_name="authentication_user",
    )

    class Meta:
        db_table = "authentication_user"
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
