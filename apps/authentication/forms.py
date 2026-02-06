import random

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm, PasswordChangeForm, AuthenticationForm, \
    UsernameField
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django_recaptcha.fields import ReCaptchaField

from bot.models import TelegramUser, UserProfile

User = get_user_model()


class UserRegistrationForm(forms.Form):
    email = forms.EmailField(
        label='Электронная почта',
        widget=forms.EmailInput(attrs={'placeholder': 'Введите вашу почту'}),
    )
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'placeholder': 'Введите пароль'}),
        min_length=8,
    )
    password_confirm = forms.CharField(
        label='Подтверждение пароля',
        widget=forms.PasswordInput(attrs={'placeholder': 'Подтвердите пароль'}),
        min_length=8,
    )
    captcha = ReCaptchaField(label='Подтверждение, что вы не робот')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                raise ValidationError('Пароли не совпадают.')
        return cleaned_data

    def save(self):
        email = self.cleaned_data['email']
        username = self.cleaned_data['email']
        password = self.cleaned_data['password']
        user = User.objects.create_user(username=username, email=email, password=password)

        # Create Fake TG User
        tg_user = TelegramUser.objects.create(
            user_id=random.randint(2345678909800, 9923456789000),
            username=username,
            subscription_status=False,
        )

        try:
            profile = UserProfile.objects.get(user=user)
        except ObjectDoesNotExist as e:
            profile = UserProfile.objects.create(user=user, telegram_user=tg_user)
        else:
            profile.telegram_user = tg_user
            profile.save()

        return user


class LoginForm(AuthenticationForm):
    username = UsernameField(widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Имя пользователя"}))
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Пароль"}),
    )

class UserPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'form-control'
    }))


class UserSetPasswordForm(SetPasswordForm):
    confirm = ReCaptchaField()
    new_password1 = forms.CharField(max_length=50, widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Новый пароль'
    }), label="Новый пароль")
    new_password2 = forms.CharField(max_length=50, widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Подтвердить новый пароль'
    }), label="Подтвердить новый пароль")


class UserPasswordChangeForm(PasswordChangeForm):
    confirm = ReCaptchaField()
    old_password = forms.CharField(max_length=50, widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Старый пароль'
    }), label='Старый пароль')
    new_password1 = forms.CharField(max_length=50, widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Новый пароль'
    }), label="Новый пароль")
    new_password2 = forms.CharField(max_length=50, widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Подтвердить новый пароль'
    }), label="Подтвердить новый пароль")