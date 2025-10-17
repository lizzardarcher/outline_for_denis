import traceback
from datetime import timedelta

from django.db.models import Min, Max

from bot.main import django_orm
from bot.models import *

# pairs_dict = {}

# logs = Logging.objects.filter(message__icontains='celery')
# [CELERY] Ошибка при списании с пользователя :
# {'type': 'error', 'id': '01995f5f-4542-705b-a067-858b98ab3795',
# 'description': "This payment_method_id doesn't exist. Specify the id of the saved payment_method",
# 'parameter': 'payment_method_id', 'code': 'invalid_request'}
# из сообщения такого плана надо добавить в pairs_dict пользователя и его payment_method_id


# for log in logs:
#     if "This payment_method_id doesn't exist" in log.message:
#         try:
#             user_id = int(log.message.split('пользователя')[1].split(':')[0].strip())
#             payment_method_id = log.message.split("id': '")[1].split("'")[0]
#
#             pairs_dict[user_id] = payment_method_id
#         except:
#             ...
#
# users = TelegramUser.objects.all()
#
# for user in users:
#     if user.user_id in pairs_dict:
#         if not user.payment_method_id:
#             if pairs_dict[user.user_id]:
#                 user.payment_method_id = pairs_dict[user.user_id]
#                 user.save()
#                 print(f"Updated user {user.user_id} with payment_method_id {pairs_dict[user.user_id]}")


# transactions = Transaction.objects.all()

# for transaction in transactions:
#     user = transaction.user
#     try:
#         if user.payment_method_id and user.subscription_status == False and transaction.payment_id:
#             # pairs_dict[transaction.user] = transaction.payment_id
#             print(f"Updated user {transaction.user.user_id} with payment_method_id {transaction.payment_id}")
#     except:
#         ...


# if __name__ == '__main__':
#     try:
#         counter = 0
#         users = TelegramUser.objects.filter(subscription_status=False, permission_revoked=False, payment_method_id__isnull=False, subscription_expiration__lt=datetime.now() - timedelta(days=3))
#         user_ids = [x.user_id for x in users]
#         payment_logs = Logging.objects.filter(user__user_id__in=user_ids, message__icontains='This payment_method is not saved')
#         payment_logs_unique_user_ids = set([x.user.user_id for x in payment_logs])
#         payment_logs = Logging.objects.filter(user__user_id__in=payment_logs_unique_user_ids).distinct("user")
#
#         print(len(payment_logs_unique_user_ids), len(payment_logs))
#
#         # for log in payment_logs:
#         #     print(counter, log.user)
#         #     counter += 1
#
#     except KeyboardInterrupt as e:
#         pass



# if __name__ == '__main__':
#     try:
#         counter = 0
#         users = TelegramUser.objects.filter(
#             subscription_status=False,
#             permission_revoked=False,
#             payment_method_id__isnull=True,
#         )
#
#         user_ids_from_telegram_users = [x.user_id for x in users]
#
#         all_relevant_payment_logs = Logging.objects.filter(user__user_id__in=user_ids_from_telegram_users, message__icontains='This payment_method is not saved')
#
#         log_ids_for_unique_users = all_relevant_payment_logs.values('user__user_id').annotate(min_id=Min('id')).values_list('min_id', flat=True)
#
#         payment_logs_deduplicated = Logging.objects.filter(id__in=log_ids_for_unique_users)
#
#         for log in payment_logs_deduplicated:
#             try:
#                 transaction = Transaction.objects.filter(user=log.user, status='succeeded').last()
#                 if transaction.description != 'Рекуррентный платеж' and transaction.payment_id and transaction.user.permission_revoked == False and transaction.user.subscription_status == False:
#                     print(counter, transaction.payment_id)
#                     # transaction.user.payment_method_id = transaction.payment_id
#                     # transaction.user.save()
#                     counter += 1
#             except:
#                 pass
#
#     except KeyboardInterrupt as e:
#         pass

vpn_key = VpnKey.objects.filter(access_url='ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpZRjEwZ0V0UGU3RUFuQTJEak9Cb2FI@185.142.33.24:22934/?outline=1#VPN').delete()