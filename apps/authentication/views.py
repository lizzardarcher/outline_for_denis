from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordChangeView, LoginView
from django.urls import reverse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.contrib import messages

from .forms import (
    UserRegistrationForm,
    UserSetPasswordForm,
    UserPasswordChangeForm,
    LoginForm,
    DashboardPasswordChangeForm,
)


def telegram_login(request):
    data = request.GET.dict()
    user = authenticate(request, data=data)

    if user:
        login(request, user)
        return redirect(reverse('profile'))
    else:
        messages.error(request, f"Authentication failed. Please, contact support.")
        return redirect(reverse('home'))



def register_view(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, 'Регистрация прошла успешно!')
            return redirect('login')
        else:
            messages.error(request, 'Ошибка регистрации, проверьте данные.')
    else:
        form = UserRegistrationForm()
    return render(request, 'account/register.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('/')


class UserLoginView(LoginView):
    template_name = 'account/login.html'
    form_class = LoginForm
    success_url = '/'

    def get_success_url(self):
        return reverse('profile')


# class UserPasswordResetView(PasswordResetView):
#     template_name = 'account/password_reset.html'
#     form_class = UserPasswordResetForm


class UserPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'account/password_reset_confirm.html'
    form_class = UserSetPasswordForm


class UserPasswordChangeView(PasswordChangeView):
    template_name = 'account/password_change.html'
    form_class = UserPasswordChangeForm


@login_required
@require_POST
def dashboard_password_change(request):
    """Смена пароля из ЛК: валидация в форме, успех — редирект в ЛК с сообщением."""
    from apps.dashboard.views import ProfileView

    form = DashboardPasswordChangeForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Пароль успешно изменён.')
        return redirect('profile')

    view = ProfileView()
    view.request = request
    view.args = ()
    view.kwargs = {}
    context = view.get_context_data()
    context['dashboard_password_form'] = form
    context['open_password_change_modal'] = True
    return render(request, 'dashboard/index.html', context)