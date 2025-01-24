from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, login
from django.urls import reverse


def telegram_login(request):
    data = request.GET.dict()
    user = authenticate(request, data=data)

    if user:
        login(request, user)
        messages.success(request, "You are now logged in successfully.")
        return redirect(reverse('profile'))
    else:
        messages.error(request, f"Authentication failed. GET: {request.GET.dict()}")
        messages.error(request, f"User: {user}")
        return redirect(reverse('home'))
