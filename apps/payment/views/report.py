from datetime import datetime
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncYear, TruncMonth

from django.views import View

from django.http import HttpResponse


from openpyxl import Workbook

from bot.models import Transaction

class TransactionExcelExportView(LoginRequiredMixin, View):
    """
    Экспорт транзакций в Excel с двумя листами:
      - Transactions: все транзакции + кол-во успешных транзакций за день/месяц/год (успешная = paid=True OR status='succeeded')
      - Income_Aggregates: агрегаты сумм amount для status='succeeded' по дням/месяцам/годам (разбивка по currency)
    """

    SUCCESS_Q = Q(paid=True) | Q(status='succeeded')  # для подсчёта успешных транзакций в листе Transactions
    AGG_SUCCESS_STATUS = 'succeeded'  # для листа Income_Aggregates фильтр status='succeeded'

    def get(self, request, *args, **kwargs):
        # -----------------------
        # Подготовка агрегатов успешных транзакций (для колонок successful_today/month/year)
        # -----------------------
        daily = (
            Transaction.objects
            .filter(self.SUCCESS_Q)
            .annotate(day=TruncDate('timestamp'))
            .values('user_id', 'day')
            .annotate(cnt=Count('id'))
        )
        monthly = (
            Transaction.objects
            .filter(self.SUCCESS_Q)
            .annotate(month=TruncMonth('timestamp'))
            .values('user_id', 'month')
            .annotate(cnt=Count('id'))
        )
        yearly = (
            Transaction.objects
            .filter(self.SUCCESS_Q)
            .annotate(year=TruncYear('timestamp'))
            .values('user_id', 'year')
            .annotate(cnt=Count('id'))
        )

        daily_map = {}
        for item in daily:
            # item['day'] — date
            key = (item['user_id'], item['day'])
            daily_map[key] = item['cnt']

        monthly_map = {}
        for item in monthly:
            # TruncMonth возвращает datetime на первый день месяца; приводим к date
            m = item['month']
            m_date = m.date() if hasattr(m, 'date') else m
            key = (item['user_id'], m_date)
            monthly_map[key] = item['cnt']

        yearly_map = {}
        for item in yearly:
            y = item['year']
            y_date = y.date() if hasattr(y, 'date') else y
            key = (item['user_id'], y_date)
            yearly_map[key] = item['cnt']

        # -----------------------
        # Подготовка агрегатов доходов для листа Income_Aggregates (status='succeeded')
        # -----------------------
        agg_qs_base = Transaction.objects.filter(status=self.AGG_SUCCESS_STATUS)

        # По дням: group by day + currency
        daily_income = (
            agg_qs_base
            .annotate(day=TruncDate('timestamp'))
            .values('day', 'currency')
            .annotate(total_amount=Sum('amount'))
            .order_by('day', 'currency')
        )

        # По месяцам: TruncMonth -> group by month + currency
        monthly_income = (
            agg_qs_base
            .annotate(month=TruncMonth('timestamp'))
            .values('month', 'currency')
            .annotate(total_amount=Sum('amount'))
            .order_by('month', 'currency')
        )

        # По годам: TruncYear -> group by year + currency
        yearly_income = (
            agg_qs_base
            .annotate(year=TruncYear('timestamp'))
            .values('year', 'currency')
            .annotate(total_amount=Sum('amount'))
            .order_by('year', 'currency')
        )

        # -----------------------
        # Создаём Excel книгу и листы
        # -----------------------
        wb = Workbook()

        # Создаём второй лист для агрегатов дохода
        ws2 = wb.create_sheet(title="Income_Aggregates")

        # Секция: по дням
        ws2.append(["Daily totals (status='succeeded')"])
        ws2.append(["date", "currency", "total_amount"])
        for item in daily_income:
            day = item['day']
            total = item['total_amount'] or Decimal('0.00')
            # Делаем строку: date (YYYY-MM-DD), currency, total
            ws2.append([day.isoformat() if hasattr(day, 'isoformat') else str(day), item['currency'], str(total)])

        # Пустая строка для визуального разделения
        ws2.append([])

        # Секция: по месяцам
        ws2.append(["Monthly totals (status='succeeded')"])
        ws2.append(["month", "currency", "total_amount"])
        for item in monthly_income:
            month = item['month']  # datetime (первый день месяца)
            # Отображаем как YYYY-MM
            if hasattr(month, 'date'):
                month_display = month.strftime("%Y-%m")
            else:
                month_display = str(month)
            total = item['total_amount'] or Decimal('0.00')
            ws2.append([month_display, item['currency'], str(total)])

        ws2.append([])

        # Секция: по годам
        ws2.append(["Yearly totals (status='succeeded')"])
        ws2.append(["year", "currency", "total_amount"])
        for item in yearly_income:
            year = item['year']  # datetime (первый день года)
            if hasattr(year, 'date'):
                year_display = year.strftime("%Y")
            else:
                year_display = str(year)
            total = item['total_amount'] or Decimal('0.00')
            ws2.append([year_display, item['currency'], str(total)])

        # -----------------------
        # Отдаём файл в ответ
        # -----------------------
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        filename = f"transactions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response
