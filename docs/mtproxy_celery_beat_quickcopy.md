# MTProxy Celery Beat quick copy

## PeriodicTask entries

Note: key sync uses SSH + `mtproxymax` CLI (no extra HTTP manage API service required).

Name: `mtproxy:healthcheck:every_2m`  
Task: `apps.mtproxy.tasks.healthcheck_mtproxy_nodes_task`  
Schedule: every `2 minutes`  
Args: `[]`  
Kwargs: `{}`

Name: `mtproxy:collect_snapshots:every_3m`  
Task: `apps.mtproxy.tasks.collect_mtproxy_usage_snapshots_task`  
Schedule: every `3 minutes`  
Args: `[]`  
Kwargs: `{}`

Name: `mtproxy:abuse_score:every_4m`  
Task: `apps.mtproxy.tasks.calculate_mtproxy_abuse_score_task`  
Schedule: every `4 minutes`  
Args: `[]`  
Kwargs: `{}`

Name: `mtproxy:revoke_inactive_subscriptions:every_10m`  
Task: `apps.mtproxy.tasks.revoke_mtproxy_keys_for_inactive_subscriptions_task`  
Schedule: every `10 minutes`  
Args: `[]`  
Kwargs: `{}`
