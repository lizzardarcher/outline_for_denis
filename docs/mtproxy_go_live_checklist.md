# MTProxy Go-Live Checklist (5-10 minutes)

Этот чеклист нужен перед запуском MTProxy функционала в рабочем режиме.

---

## 1) Применить миграции

```bash
python3 manage.py migrate
```

Ожидаемый результат:
- миграции `apps.mtproxy` применены;
- ошибок по таблицам нет.

---

## 2) Проверить Celery процессы

Убедиться, что запущены:
- `celery worker`
- `celery beat`

В проде проверить значение:
- `CELERY_TASK_ALWAYS_EAGER = False`

---

## 3) Проверить расписание (django-celery-beat)

В админке `admindomvpnx` -> `Periodic tasks` должны быть включены:

1. `apps.mtproxy.tasks.healthcheck_mtproxy_nodes_task` (каждые 2 мин)
2. `apps.mtproxy.tasks.collect_mtproxy_usage_snapshots_task` (каждые 3 мин)
3. `apps.mtproxy.tasks.calculate_mtproxy_abuse_score_task` (каждые 4 мин)
4. `apps.mtproxy.tasks.revoke_mtproxy_keys_for_inactive_subscriptions_task` (каждые 10 мин)

Быстрая шпаргалка по копипасту:
- `docs/mtproxy_celery_beat_quickcopy.md`

---

## 4) Проверить настройку ноды в админке

Путь: `admindomvpnx` -> `MTProto ноды`

Для каждой рабочей ноды проверить поля:
- `host`
- `proxy_port`
- `ssh_port`
- `ssh_username`
- `ssh_password`
- `capacity`
- `is_active = True`

Опционально:
- `metrics_url` (если есть endpoint метрик)
- `install_script` (если нужен кастомный деплой)

---

## 5) Установить ПО на ноду

В `MTProto ноды`:
- выбрать ноду;
- action: `Установить ПО на выбранные ноды`.

Ожидаемый результат:
- `install_state = installed`
- `is_software_installed = True`
- в `MTProto события` есть `install_success`.

---

## 6) Проверить health-check ноды

В `MTProto ноды` action:
- `Запустить health-check всех нод`.

Ожидаемый результат:
- `health_state = up`
- `last_healthcheck_at` обновляется.

---

## 7) Smoke test выдачи ключа (сайт)

Под пользователем, у которого `TelegramUser.username == "megafoll"`:

1. Открыть `/dashboard/profile/`
2. Вкладка `TG Proxy` -> `Получить/проверить ключ`

Ожидаемый результат:
- создается `MTProto ключ` со статусом `active`;
- появляется `tg://proxy?...` ссылка;
- в `MTProto события` есть `key_issued` и `SYNC/SSH`.

---

## 8) Smoke test перевыдачи ключа (сайт)

В той же вкладке:
- нажать `Перевыдать ключ`.

Ожидаемый результат:
- старый ключ -> `revoked`
- новый ключ -> `active`
- события `key_revoked` + `key_reissued`.

---

## 9) Smoke test в боте

Под тем же пользователем (`megafoll`):
- открыть меню бота;
- проверить кнопку `🛰 TG Proxy`;
- выполнить выдачу и перевыдачу.

Ожидаемый результат:
- поведение совпадает с сайтом;
- ключи отражаются в одной и той же модели `ProxyAccessKey`.

---

## 10) Проверка отзыва при отключении подписки

### Вариант A (ручной)
- отменить подписку на сайте или в боте.

Ожидаемый результат:
- активные proxy-ключи пользователя становятся `revoked`;
- в событиях есть запись с причиной (`manual_cancel_site` / `manual_cancel_bot`).

### Вариант B (автоматический)
- пользователь с `subscription_status=False`;
- дождаться `revoke_mtproxy_keys_for_inactive_subscriptions_task`.

Ожидаемый результат:
- активных ключей у пользователя не остается.

---

## 11) Проверка anti-abuse пайплайна

1. Создать/убедиться, что есть `MTProto срезы метрик`.
2. Запустить action `Пересчитать anti-abuse score`.

Ожидаемый результат:
- обновляется `abuse_score` у `MTProto ключей`;
- при порогах появляются события `abuse_flag`;
- при критическом пороге ключ отзывается автоматически.

---

## 12) Проверка логов и проблемных точек

Где смотреть:
- `admindomvpnx` -> `MTProto события`
- `admindomvpnx` -> `Логи` (`bot.Logging`)

Типовые проблемы:
- SSH auth error -> неверные SSH креды;
- `mtproxymax` command not found -> ПО не установлено/не в PATH;
- `health_state=down` -> порт закрыт или сервис не поднят;
- нет snapshots -> не работает `metrics_url` и/или задачи beat.

---

## 13) Готовность к запуску

Считать систему готовой, если выполнены все пункты:
- [ ] миграции применены
- [ ] worker + beat работают
- [ ] schedule активен
- [ ] ноды в `installed + up`
- [ ] выдача/перевыдача работают (сайт+бот)
- [ ] revoke по подписке работает
- [ ] anti-abuse score обновляется
