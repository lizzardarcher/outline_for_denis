from bot.main import django_orm
from bot.models import *

pairs_dict = {}

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


if __name__ == '__main__':
    try:
        counter = 0
        users = TelegramUser.objects.filter(subscription_status=False)

        for user in users:
            try:
                if user.payment_method_id:
                    transaction = Transaction.objects.filter(user=user, payment_id__isnull=False).first()
                    user.payment_method_id = transaction.payment_id
                    user.save()
                    print(f"{counter}. Updated user {user.user_id} old payment_method_id {user.payment_method_id} with payment_method_id {transaction.payment_id}")
                    counter += 1
            except:
                pass
    except KeyboardInterrupt as e:
        pass