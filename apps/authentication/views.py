from django.contrib.auth import authenticate, login
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms import UserRegistrationForm

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
