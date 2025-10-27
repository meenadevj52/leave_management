import uuid
from django.db import models
from django.utils import timezone
from datetime import date
from decimal import Decimal

class Employee(models.Model):

    ROLE_CHOICES = [
        ('HR', 'HR'),
        ('HR_MANAGER', 'HR Manager'),
        ('CHRO', 'CHRO'),
        ('MANAGER', 'Manager'),
        ('DEPARTMENT_HEAD', 'Department Head'),
        ('TEAM_LEAD', 'Team Lead'),
        ('EMPLOYEE', 'Employee'),
        ('ADMIN', 'Admin'),
        ('CFO', 'CFO'),
    ]

    EMPLOYMENT_TYPE_CHOICES = [
        ('Permanent', 'Permanent'),
        ('Probation', 'Probation'),
        ('Contract', 'Contract'),
        ('Intern', 'Intern'),
        ('Temporary', 'Temporary'),
    ]

    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
        ('Prefer not to say', 'Prefer not to say'),
    ]

    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True, null=True, blank=True)
    
    # Personal Information
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True, null=True)
    nid = models.CharField(max_length=50, blank=True, null=True, verbose_name="National ID")
    
    # Employment Information
    designation = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Job title (e.g., 'Senior Software Engineer', 'Backend Developer')"
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        help_text="System role for permissions"
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Department name (e.g., 'IT', 'Sales', 'HR')"
    )
    
    # Reporting Structure
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text="Direct reporting manager"
    )
    department_head = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='department_members',
        help_text="Department head (for approval chain)"
    )
    
    # Employment Details
    joining_date = models.DateField()
    employment_type = models.CharField(max_length=50, choices=EMPLOYMENT_TYPE_CHOICES)
    is_permanent = models.BooleanField(default=True)
    employment_type_updated_from = models.DateField(
        null=True,
        blank=True,
        help_text="Date when employment type changed (e.g., Probation to Permanent)"
    )
    
    # Salary Information (for leave encashment)
    monthly_basic_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Monthly basic salary for encashment calculation"
    )
    monthly_gross_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Monthly gross salary including allowances"
    )
    salary_per_day = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Daily salary rate for leave encashment (auto-calculated or manual)"
    )
    hourly_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Hourly rate for hour-based calculations"
    )
    
    # Notice Period
    is_in_notice_period = models.BooleanField(
        default=False,
        help_text="Is employee serving notice period?"
    )
    notice_period_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when notice period started"
    )
    notice_period_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expected last working day"
    )
    
    # Profile & Media
    profile_image = models.CharField(max_length=255, blank=True, null=True)
    signature_image = models.CharField(max_length=255, blank=True, null=True)
    
    # Additional Information
    is_introduced = models.BooleanField(default=False)
    emergency_contact_info = models.TextField(
        blank=True,
        null=True,
        help_text="JSON or text with emergency contact details"
    )
    reference = models.TextField(blank=True, null=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    termination_date = models.DateField(null=True, blank=True)
    termination_reason = models.TextField(blank=True, null=True)
    
    # Metadata
    created_by = models.UUIDField()
    updated_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_id', 'email']),
            models.Index(fields=['tenant_id', 'department']),
            models.Index(fields=['tenant_id', 'manager']),
            models.Index(fields=['employment_type']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'

    def __str__(self):
        return f"{self.full_name} ({self.designation})"

    # Properties and Helper Methods

    @property
    def full_name(self):
        """Return full name of employee."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def tenure_days(self):
        """Calculate tenure in days."""
        if not self.joining_date:
            return 0
        end_date = self.termination_date if self.termination_date else date.today()
        return (end_date - self.joining_date).days

    @property
    def tenure_months(self):
        """Calculate tenure in months."""
        return self.tenure_days // 30

    @property
    def tenure_years(self):
        """Calculate tenure in years."""
        return self.tenure_months // 12

    @property
    def is_on_probation(self):
        """Check if employee is on probation."""
        return self.employment_type == 'Probation'

    @property
    def probation_end_date(self):
        """Calculate expected probation end date (assuming 6 months)."""
        if self.employment_type == 'Probation' and self.joining_date:
            from datetime import timedelta
            return self.joining_date + timedelta(days=180)
        return None

    def calculate_daily_salary(self, calculation_base='PER_DAY_SALARY'):
        """
        Calculate daily salary based on different bases.
        
        Args:
            calculation_base: One of PER_DAY_SALARY, MONTHLY_BASIC_SALARY, MONTHLY_GROSS_SALARY, PER_HOUR_SALARY
        
        Returns:
            Decimal: Daily salary amount
        """
        if calculation_base == 'PER_DAY_SALARY':
            return self.salary_per_day
        elif calculation_base == 'MONTHLY_BASIC_SALARY':
            # Assuming 30 days per month
            return self.monthly_basic_salary / Decimal('30')
        elif calculation_base == 'MONTHLY_GROSS_SALARY':
            return self.monthly_gross_salary / Decimal('30')
        elif calculation_base == 'PER_HOUR_SALARY':
            # Assuming 8 hours per day
            return self.hourly_rate * Decimal('8')
        else:
            return self.salary_per_day

    def get_manager_chain(self):
        chain = []
        current = self.manager
        while current and current not in chain:  # Prevent circular references
            chain.append(current)
            current = current.manager
        return chain

    def is_eligible_for_leave_type(self, leave_type):
        if self.employment_type in ['Intern', 'Temporary']:
            # Only sick leave allowed
            return leave_type in ['Sick', 'Emergency']
        
        if self.employment_type == 'Probation':
            # No annual or casual leave during probation
            return leave_type not in ['Annual', 'Casual']
        
        # Permanent and Contract employees can take all types
        return True

    def save(self, *args, **kwargs):
        if not self.salary_per_day and self.monthly_basic_salary:
            self.salary_per_day = self.monthly_basic_salary / Decimal('30')
        
        super().save(*args, **kwargs)


class EmployeeDocument(models.Model):
    
    DOCUMENT_TYPE_CHOICES = [
        ('ID_PROOF', 'ID Proof'),
        ('ADDRESS_PROOF', 'Address Proof'),
        ('EDUCATIONAL_CERTIFICATE', 'Educational Certificate'),
        ('EXPERIENCE_LETTER', 'Experience Letter'),
        ('MEDICAL_CERTIFICATE', 'Medical Certificate'),
        ('FITNESS_CERTIFICATE', 'Fitness Certificate'),
        ('OFFER_LETTER', 'Offer Letter'),
        ('RESIGNATION_LETTER', 'Resignation Letter'),
        ('OTHER', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES)
    document_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_size = models.IntegerField(help_text="File size in bytes")
    
    uploaded_by = models.UUIDField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.document_type}"