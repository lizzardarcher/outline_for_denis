from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Пользователь сайта / админки (таблица authentication_user).
    PK — bigint (BigAutoField), не совпадает с Telegram user_id.

    M2M на auth.Group / auth.Permission с отдельными related_name, чтобы модель
    не конфликтовала с django.contrib.auth.models.User до переключения AUTH_USER_MODEL.
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
