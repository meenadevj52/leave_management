import uuid
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from django.core.exceptions import ValidationError
from employees.models import Employee, EmployeeDocument

class EmployeeModelTest(TestCase):
    def setUp(self):
        self.employee_data = {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@example.com',
            'role': 'EMPLOYEE',
            'joining_date': date(2023, 1, 1),
            'employment_type': 'Permanent',
            'created_by': uuid.uuid4(),
            'updated_by': uuid.uuid4(),
            'monthly_basic_salary': Decimal('50000.00'),
            'monthly_gross_salary': Decimal('70000.00'),
        }
        self.employee = Employee.objects.create(**self.employee_data)

    def test_employee_creation(self):
        self.assertTrue(isinstance(self.employee, Employee))
        self.assertEqual(str(self.employee), f"John Doe ({None})")
        self.assertTrue(isinstance(self.employee.id, uuid.UUID))

    def test_full_name_property(self):
        self.assertEqual(self.employee.full_name, "John Doe")
        
        self.employee.last_name = ""
        self.assertEqual(self.employee.full_name, "John")

    def test_tenure_calculations(self):
        today = date(2025, 1, 1)
        
        original_date = Employee.tenure_days.fget
        Employee.tenure_days = property(lambda self: (today - self.joining_date).days)
        
        self.assertEqual(self.employee.tenure_days, 731)
        self.assertEqual(self.employee.tenure_months, 24)
        self.assertEqual(self.employee.tenure_years, 2)
        
        Employee.tenure_days = original_date

    def test_probation_status(self):
        self.assertFalse(self.employee.is_on_probation)
        self.assertIsNone(self.employee.probation_end_date)

        self.employee.employment_type = 'Probation'
        self.assertTrue(self.employee.is_on_probation)
        expected_end_date = self.employee.joining_date + timedelta(days=180)
        self.assertEqual(self.employee.probation_end_date, expected_end_date)

    def test_daily_salary_calculation(self):
        self.employee.salary_per_day = Decimal('2000.00')
        self.assertEqual(
            self.employee.calculate_daily_salary('PER_DAY_SALARY'),
            Decimal('2000.00')
        )

        self.assertEqual(
            self.employee.calculate_daily_salary('MONTHLY_BASIC_SALARY'),
            Decimal('50000.00') / Decimal('30')
        )

        self.assertEqual(
            self.employee.calculate_daily_salary('MONTHLY_GROSS_SALARY'),
            Decimal('70000.00') / Decimal('30')
        )

        self.employee.hourly_rate = Decimal('250.00')
        self.assertEqual(
            self.employee.calculate_daily_salary('PER_HOUR_SALARY'),
            Decimal('250.00') * Decimal('8')
        )

    def test_manager_chain(self):
        dept_head = Employee.objects.create(
            first_name='Department',
            last_name='Head',
            email='dept.head@example.com',
            role='DEPARTMENT_HEAD',
            joining_date=date(2023, 1, 1),
            employment_type='Permanent',
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        manager = Employee.objects.create(
            first_name='Team',
            last_name='Manager',
            email='team.manager@example.com',
            role='MANAGER',
            joining_date=date(2023, 1, 1),
            employment_type='Permanent',
            manager=dept_head,
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.employee.manager = manager
        self.employee.save()

        manager_chain = self.employee.get_manager_chain()
        self.assertEqual(len(manager_chain), 2)
        self.assertEqual(manager_chain[0], manager)
        self.assertEqual(manager_chain[1], dept_head)

    def test_leave_eligibility(self):
        self.assertTrue(self.employee.is_eligible_for_leave_type('Annual'))
        self.assertTrue(self.employee.is_eligible_for_leave_type('Casual'))
        self.assertTrue(self.employee.is_eligible_for_leave_type('Sick'))

        self.employee.employment_type = 'Probation'
        self.assertFalse(self.employee.is_eligible_for_leave_type('Annual'))
        self.assertFalse(self.employee.is_eligible_for_leave_type('Casual'))
        self.assertTrue(self.employee.is_eligible_for_leave_type('Sick'))

        self.employee.employment_type = 'Intern'
        self.assertFalse(self.employee.is_eligible_for_leave_type('Annual'))
        self.assertTrue(self.employee.is_eligible_for_leave_type('Emergency'))

    def test_auto_salary_per_day_calculation(self):
        employee = Employee.objects.create(
            first_name='Jane',
            last_name='Doe',
            email='jane.doe@example.com',
            role='EMPLOYEE',
            joining_date=date(2023, 1, 1),
            employment_type='Permanent',
            monthly_basic_salary=Decimal('60000.00'),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        expected_per_day = Decimal('60000.00') / Decimal('30')
        self.assertEqual(employee.salary_per_day, expected_per_day)


class EmployeeDocumentModelTest(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create(
            first_name='John',
            last_name='Doe',
            email='john.doe@example.com',
            role='EMPLOYEE',
            joining_date=date(2023, 1, 1),
            employment_type='Permanent',
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.document_data = {
            'employee': self.employee,
            'document_type': 'ID_PROOF',
            'document_name': 'National ID Card',
            'file_path': '/documents/national_id.pdf',
            'file_size': 1024 * 1024,
            'uploaded_by': uuid.uuid4(),
        }

    def test_document_creation(self):
        document = EmployeeDocument.objects.create(**self.document_data)
        self.assertTrue(isinstance(document, EmployeeDocument))
        self.assertTrue(isinstance(document.id, uuid.UUID))
        self.assertEqual(str(document), f"John Doe - ID_PROOF")

    def test_document_relationship(self):
        document = EmployeeDocument.objects.create(**self.document_data)
        self.assertEqual(document.employee, self.employee)
        self.assertEqual(self.employee.documents.count(), 1)
        self.assertEqual(self.employee.documents.first(), document)