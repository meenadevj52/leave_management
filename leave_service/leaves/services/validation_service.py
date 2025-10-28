from datetime import datetime, timedelta
from decimal import Decimal
from ..models import LeaveBalance, Holiday, LeaveApplication


class LeaveValidationService:
    
    @staticmethod
    def calculate_leave_days(start_date, end_date, is_half_day, tenant_id):
        if is_half_day:
            return Decimal('0.5'), 0
        
        holidays = Holiday.objects.filter(
            tenant_id=tenant_id,
            date__gte=start_date,
            date__lte=end_date,
            is_optional=False
        ).values_list('date', flat=True)
        
        current_date = start_date
        working_days = 0
        holiday_count = 0
        
        while current_date <= end_date:
            if current_date.weekday() < 5:
                if current_date not in holidays:
                    working_days += 1
                else:
                    holiday_count += 1
            current_date += timedelta(days=1)
        
        return Decimal(str(working_days)), holiday_count
    
    @staticmethod
    def check_leave_overlap(employee_id, start_date, end_date, exclude_id=None):
        query = LeaveApplication.objects.filter(
            employee_id=employee_id,
            status__in=['PENDING', 'APPROVED']
        ).exclude(
            end_date__lt=start_date
        ).exclude(
            start_date__gt=end_date
        )
        
        if exclude_id:
            query = query.exclude(id=exclude_id)
        
        return query.exists()
    
    @staticmethod
    def get_or_create_balance(tenant_id, employee_id, leave_type, year, total_allocated=0):
        balance, created = LeaveBalance.objects.get_or_create(
            tenant_id=tenant_id,
            employee_id=employee_id,
            leave_type=leave_type,
            year=year,
            defaults={'total_allocated': total_allocated}
        )
        return balance
    
    @staticmethod
    def check_sufficient_balance(employee_id, leave_type, requested_days, year):
        try:
            balance = LeaveBalance.objects.get(
                employee_id=employee_id,
                leave_type=leave_type,
                year=year
            )
            return balance.available >= requested_days
        except LeaveBalance.DoesNotExist:
            return False
    
    @staticmethod
    def calculate_encashment(policy, employee_balance, requested_days, salary_per_day):
        max_encashable = Decimal(str(policy.get('encashment', 0)))
        
        if requested_days > max_encashable:
            return {
                'allowed': False,
                'reason': f'Max encashable days is {max_encashable}',
                'amount': 0
            }
        
        if requested_days > employee_balance:
            return {
                'allowed': False,
                'reason': 'Insufficient balance',
                'amount': 0
            }
        
        multiplier = Decimal(str(policy.get('multiplier', 1.0)))
        amount = requested_days * salary_per_day * multiplier
        
        return {
            'allowed': True,
            'amount': float(amount),
            'days': float(requested_days),
            'multiplier': float(multiplier),
            'calculation_base': policy.get('calculation_base', 'PER_DAY_SALARY')
        }