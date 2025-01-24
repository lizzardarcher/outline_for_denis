from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render
from django.views.generic import TemplateView


class ProfileView(SuccessMessageMixin, TemplateView):
    template_name = 'dashboard/index.html'