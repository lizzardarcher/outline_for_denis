import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class SystemLogView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/system_log.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        log_path = '/opt/outline/bot/main/log/bot_log.log'
        log_content = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                log_content = f.readlines()[-100:]
        else:
            log_content = ['Лог-файл не найден.']
        context['log_content'] = log_content
        return context

