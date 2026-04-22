# MTProxy: Celery Beat manual

Этот документ описывает, какие задачи нужно добавить в `django-celery-beat` (через БД), чтобы MTProxy работал в автоматическом режиме.

Синхронизация ключей с нодами выполняется через SSH и команды `mtproxymax` (дополнительный manage API на нодах не требуется).

Полный go-live чеклист:
- `docs/mtproxy_go_live_checklist.md`

## 0) Важно перед настройкой schedule

1. Применить миграции:
   - `python3 manage.py migrate`
2. Убедиться, что запущены:
   - Celery worker
   - Celery beat
3. В проде отключить eager-режим:
   - в `outline_for_denis/settings.py` значение `CELERY_TASK_ALWAYS_EAGER` должно быть `False`.

## 1) Обязательные задачи для MTProxy

### 1. Health-check нод

- **Task:** `apps.mtproxy.tasks.healthcheck_mtproxy_nodes_task`
- **Interval:** каждые `2 минуты`
- **Enabled:** `True`
- **Назначение:**
  - проверка доступности proxy-порта нод;
  - обновление `health_state`;
  - автосоздание `ProxyUsageSnapshot` при каждом цикле.

---

### 2. Явный сбор usage snapshots

- **Task:** `apps.mtproxy.tasks.collect_mtproxy_usage_snapshots_task`
- **Interval:** каждые `3 минуты`
- **Enabled:** `True`
- **Args/Kwargs:** пусто (без параметров — собрать по всем нодам)
- **Назначение:**
  - дополнительный сбор метрик (в т.ч. если `healthcheck` временно не запускался).

> Примечание: если метрики с ноды недоступны, создаются fallback-снимки. Это нормально для MVP.

---

### 3. Расчет anti-abuse score

- **Task:** `apps.mtproxy.tasks.calculate_mtproxy_abuse_score_task`
- **Interval:** каждые `4 минуты`
- **Enabled:** `True`
- **Назначение:**
  - расчет `abuse_score` по последним snapshots;
  - запись событий abuse;
  - авто-отзыв ключа при критическом пороге.

---

### 4. Отзыв ключей у пользователей без подписки

- **Task:** `apps.mtproxy.tasks.revoke_mtproxy_keys_for_inactive_subscriptions_task`
- **Interval:** каждые `10 минут`
- **Enabled:** `True`
- **Назначение:**
  - гарантирует, что у пользователей с `subscription_status=False` не останется активных proxy ключей.

## 2) Рекомендуемый порядок запуска в рамках цикла

Чтобы расчет score шел по свежим данным, используйте интервалы в таком порядке:

1. `healthcheck_mtproxy_nodes_task` (2 мин)
2. `collect_mtproxy_usage_snapshots_task` (3 мин)
3. `calculate_mtproxy_abuse_score_task` (4 мин)
4. `revoke_mtproxy_keys_for_inactive_subscriptions_task` (10 мин)

Этого достаточно, чтобы score считался автоматически без ручного ввода.

## 3) Как создать задачи в админке

Путь: `admindomvpnx` -> `Periodic tasks` -> `Add periodic task`.

Для каждой задачи:

1. Создать/выбрать `IntervalSchedule`.
2. Указать:
   - `Name` (любое понятное)
   - `Task` (точное dotted path из раздела выше)
   - `Enabled = True`
3. Сохранить.

## 4) Примеры имен задач

- `mtproxy:healthcheck:every_2m`
- `mtproxy:collect_snapshots:every_3m`
- `mtproxy:abuse_score:every_4m`

## 5) Быстрая диагностика

Если score не обновляется:

1. Проверить, что в `PeriodicTask` задачи включены (`enabled`).
2. Проверить, что `celery beat` и `celery worker` действительно запущены.
3. Проверить логи и события:
   - `apps.mtproxy.models.ProxyEvent`
   - `bot.models.Logging`
4. Проверить наличие snapshots:
   - `MTProto срезы метрик` в админке.
