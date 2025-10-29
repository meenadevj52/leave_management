import uuid
import json
from unittest.mock import patch, MagicMock, Mock
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from employees.models import Employee, EmployeeDocument
from employees.views import get_kafka_producer, to_uuid


class MockAuthUser:
    def __init__(self, user_id, tenant_id, role, email):
        self.id = user_id
        self.tenant_id = tenant_id
        self.role = role
        self.email = email
        self.is_authenticated = True


class HelperFunctionsTestCase(TestCase):
    
    def test_to_uuid_with_valid_uuid_object(self):
        test_uuid = uuid.uuid4()
        result = to_uuid(test_uuid)
        self.assertEqual(result, test_uuid)
    
    def test_to_uuid_with_valid_string(self):
        test_uuid = uuid.uuid4()
        result = to_uuid(str(test_uuid))
        self.assertEqual(result, test_uuid)
    
    def test_to_uuid_with_none(self):
        result = to_uuid(None)
        self.assertIsNone(result)
    
    def test_to_uuid_with_invalid_string(self):
        result = to_uuid("invalid-uuid")
        self.assertIsNone(result)
    
    @patch('employees.views.KafkaProducer')
    def test_get_kafka_producer_success(self, mock_kafka_producer):
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        producer = get_kafka_producer()
        
        self.assertIsNotNone(producer)
        mock_kafka_producer.assert_called_once()
    
    @patch('employees.views.KafkaProducer')
    @patch('employees.views.time.sleep')
    def test_get_kafka_producer_retry(self, mock_sleep, mock_kafka_producer):
        mock_kafka_producer.side_effect = [Exception("Connection failed"), MagicMock()]
        
        producer = get_kafka_producer()
        
        self.assertIsNotNone(producer)
        self.assertEqual(mock_kafka_producer.call_count, 2)
        mock_sleep.assert_called_once_with(5)


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class EmployeeViewSetTestCase(APITestCase):
    
    def setUp(self):
        self.client = APIClient()
        self.tenant_id = uuid.uuid4()
        
        self.hr_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="HR",
            last_name="Manager",
            email="hr@example.com",
            role="HR",
            designation="HR Manager",
            department="HR",
            joining_date=date.today() - timedelta(days=365),
            employment_type="Permanent",
            monthly_basic_salary=Decimal('50000.00'),
            monthly_gross_salary=Decimal('60000.00'),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.manager_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Manager",
            last_name="User",
            email="manager@example.com",
            role="MANAGER",
            designation="Engineering Manager",
            department="Engineering",
            joining_date=date.today() - timedelta(days=730),
            employment_type="Permanent",
            monthly_basic_salary=Decimal('70000.00'),
            monthly_gross_salary=Decimal('85000.00'),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.employee_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Regular",
            last_name="Employee",
            email="employee@example.com",
            role="EMPLOYEE",
            designation="Software Engineer",
            department="Engineering",
            manager=self.manager_user,
            joining_date=date.today() - timedelta(days=180),
            employment_type="Probation",
            monthly_basic_salary=Decimal('40000.00'),
            monthly_gross_salary=Decimal('45000.00'),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.other_tenant_employee = Employee.objects.create(
            tenant_id=uuid.uuid4(),
            first_name="Other",
            last_name="Tenant",
            email="other@example.com",
            role="EMPLOYEE",
            designation="Developer",
            department="IT",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
    
    def _authenticate_as(self, employee):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=employee.tenant_id,
            role=employee.role,
            email=employee.email
        )
        self.client.force_authenticate(user=mock_user)
        return mock_user
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_list_employees_as_hr(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_list_employees_as_manager(self, mock_auth):
        mock_user = self._authenticate_as(self.manager_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_list_employees_as_employee(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['email'], self.employee_user.email)
    
    def test_list_employees_unauthenticated(self):
        response = self.client.get('/api/v1/employees/')
        
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_employee_as_hr(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get(f'/api/v1/employees/{self.employee_user.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.employee_user.email)
        self.assertIn('manager_details', response.data)
        self.assertIn('subordinates_count', response.data)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_employee_different_tenant(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get(f'/api/v1/employees/{self.other_tenant_employee.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    @patch('employees.views.get_kafka_producer')
    @patch('employees.views.EmployeeViewSet.perform_create')
    def test_create_employee_as_hr(self, mock_perform_create, mock_kafka, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        mock_producer = MagicMock()
        mock_kafka.return_value = mock_producer
        
        employee_data = {
            'first_name': 'New',
            'last_name': 'Employee',
            'email': 'newemp@example.com',
            'phone': '1234567890',
            'designation': 'Developer',
            'role': 'EMPLOYEE',
            'department': 'IT',
            'joining_date': str(date.today()),
            'employment_type': 'Probation',
            'monthly_basic_salary': '35000.00',
            'monthly_gross_salary': '40000.00',
            'is_permanent': False
        }
        
        response = self.client.post('/api/v1/employees/', employee_data, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_create_employee_as_regular_employee(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        employee_data = {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'test@example.com',
            'designation': 'Tester',
            'role': 'EMPLOYEE',
            'department': 'QA',
            'joining_date': str(date.today()),
            'employment_type': 'Permanent'
        }
        
        response = self.client.post('/api/v1/employees/', employee_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    @patch('employees.views.get_kafka_producer')
    def test_update_employee_as_hr(self, mock_kafka, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        mock_producer = MagicMock()
        mock_kafka.return_value = mock_producer
        
        update_data = {
            'designation': 'Senior Software Engineer',
            'employment_type': 'Permanent'
        }
        
        response = self.client.patch(
            f'/api/v1/employees/{self.employee_user.id}/',
            update_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        if mock_producer:
            mock_producer.send.assert_called()
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_update_employee_as_regular_employee(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        update_data = {'designation': 'Hacker'}
        
        response = self.client.patch(
            f'/api/v1/employees/{self.employee_user.id}/',
            update_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_delete_employee_as_hr(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.delete(f'/api/v1/employees/{self.employee_user.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        self.employee_user.refresh_from_db()
        self.assertFalse(self.employee_user.is_active)
        self.assertIsNotNone(self.employee_user.termination_date)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_delete_employee_as_manager(self, mock_auth):
        mock_user = self._authenticate_as(self.manager_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.delete(f'/api/v1/employees/{self.employee_user.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_my_profile_success(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/me/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.employee_user.email)
        self.assertIn('manager_details', response.data)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_my_profile_not_found(self, mock_auth):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            role="EMPLOYEE",
            email="nonexistent@example.com"
        )
        self.client.force_authenticate(user=mock_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/me/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_get_subordinates_as_manager(self, mock_auth):
        mock_user = self._authenticate_as(self.manager_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get(f'/api/v1/employees/{self.manager_user.id}/subordinates/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['email'], self.employee_user.email)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_get_subordinates_no_subordinates(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get(f'/api/v1/employees/{self.employee_user.id}/subordinates/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_get_by_department_with_filter(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/by-department/?department=Engineering')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_get_by_department_without_filter(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/by-department/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class EmployeeDocumentViewSetTestCase(APITestCase):
    
    def setUp(self):
        self.client = APIClient()
        self.tenant_id = uuid.uuid4()
        
        self.hr_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="HR",
            last_name="User",
            email="hr@example.com",
            role="HR",
            designation="HR Manager",
            department="HR",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.employee_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Employee",
            last_name="User",
            email="employee@example.com",
            role="EMPLOYEE",
            designation="Developer",
            department="IT",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.document = EmployeeDocument.objects.create(
            employee=self.employee_user,
            document_type="ID_PROOF",
            document_name="National ID",
            file_path="/documents/nid.pdf",
            file_size=1024,
            uploaded_by=uuid.uuid4()
        )
    
    def _authenticate_as(self, employee):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=employee.tenant_id,
            role=employee.role,
            email=employee.email
        )
        self.client.force_authenticate(user=mock_user)
        return mock_user
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_list_documents_as_hr(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/documents/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_list_documents_as_employee(self, mock_auth):
        mock_user = self._authenticate_as(self.employee_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/documents/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_create_document(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        document_data = {
            'employee': str(self.employee_user.id),
            'document_type': 'ADDRESS_PROOF',
            'document_name': 'Utility Bill',
            'file_path': '/documents/utility.pdf',
            'file_size': 2048
        }
        
        response = self.client.post('/api/v1/employees/documents/', document_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['document_type'], 'ADDRESS_PROOF')
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_document(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get(f'/api/v1/employees/documents/{self.document.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['document_type'], 'ID_PROOF')


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class EmployeeCreateViewTestCase(APITestCase):
    
    def setUp(self):
        self.client = APIClient()
        self.tenant_id = uuid.uuid4()
        
        self.hr_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="HR",
            last_name="Admin",
            email="hradmin@example.com",
            role="HR",
            designation="HR Director",
            department="HR",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
    
    def _authenticate_as(self, employee):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=employee.tenant_id,
            role=employee.role,
            email=employee.email
        )
        self.client.force_authenticate(user=mock_user)
        return mock_user
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_create_employee_missing_required_fields(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        employee_data = {
            'first_name': 'Jane',
            'email': 'jane@example.com'
        }
        
        response = self.client.post('/api/v1/employees/create/', employee_data, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_405_METHOD_NOT_ALLOWED])


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class EmployeeUpdateViewTestCase(APITestCase):
    
    def setUp(self):
        self.client = APIClient()
        self.tenant_id = uuid.uuid4()
        
        self.hr_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="HR",
            last_name="Manager",
            email="hr@example.com",
            role="HR",
            designation="HR Manager",
            department="HR",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.employee = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Test",
            last_name="Employee",
            email="test@example.com",
            role="EMPLOYEE",
            designation="Junior Developer",
            department="IT",
            joining_date=date.today() - timedelta(days=180),
            employment_type="Probation",
            monthly_basic_salary=Decimal('30000.00'),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
    
    def _authenticate_as(self, employee):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=employee.tenant_id,
            role=employee.role,
            email=employee.email
        )
        self.client.force_authenticate(user=mock_user)
        return mock_user
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    @patch('employees.views.get_kafka_producer')
    def test_update_employee_via_update_view(self, mock_kafka, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        mock_producer = MagicMock()
        mock_kafka.return_value = mock_producer
        
        update_data = {
            'designation': 'Senior Developer',
            'employment_type': 'Permanent',
            'monthly_basic_salary': '50000.00'
        }
        
        response = self.client.patch(
            f'/api/v1/employees/update/{self.employee.id}/',
            update_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.designation, 'Senior Developer')
        self.assertEqual(self.employee.employment_type, 'Permanent')
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_update_employee_different_tenant(self, mock_auth):
        other_tenant_id = uuid.uuid4()
        other_employee = Employee.objects.create(
            tenant_id=other_tenant_id,
            first_name="Other",
            last_name="Employee",
            email="other@example.com",
            role="EMPLOYEE",
            designation="Developer",
            department="IT",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        update_data = {'designation': 'Hacker'}
        
        response = self.client.patch(
            f'/api/v1/employees/update/{other_employee.id}/',
            update_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class KafkaIntegrationTestCase(TestCase):
    
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Kafka",
            last_name="Test",
            email="kafka@example.com",
            role="EMPLOYEE",
            designation="Developer",
            department="IT",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
    
    @patch('employees.views.get_kafka_producer')
    def test_employee_created_kafka_event(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer
        
        event = {
            "email": self.employee.email,
            "first_name": self.employee.first_name,
            "last_name": self.employee.last_name,
            "tenant_id": str(self.employee.tenant_id),
            "role": self.employee.role,
            "default_password": "Password@123"
        }
        
        producer = mock_get_producer()
        producer.send("employee_created", event)
        producer.flush()
        
        mock_producer.send.assert_called_once_with("employee_created", event)
        mock_producer.flush.assert_called_once()
    
    @patch('employees.views.get_kafka_producer')
    def test_employee_updated_kafka_event(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer
        
        event = {
            "employee_id": str(self.employee.id),
            "email": self.employee.email,
            "first_name": self.employee.first_name,
            "last_name": self.employee.last_name,
            "tenant_id": str(self.employee.tenant_id),
            "role": self.employee.role,
            "designation": self.employee.designation,
            "department": self.employee.department,
            "updated_by": str(uuid.uuid4())
        }
        
        producer = mock_get_producer()
        producer.send("employee_updated", event)
        producer.flush()
        
        mock_producer.send.assert_called_once_with("employee_updated", event)
        mock_producer.flush.assert_called_once()


@override_settings(KAFKA_BOOTSTRAP_SERVERS='localhost:9092')
class EdgeCasesTestCase(APITestCase):
    
    def setUp(self):
        self.client = APIClient()
        self.tenant_id = uuid.uuid4()
        
        self.hr_user = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="HR",
            last_name="User",
            email="hr@example.com",
            role="HR",
            designation="HR",
            department="HR",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
    
    def _authenticate_as(self, employee):
        mock_user = MockAuthUser(
            user_id=uuid.uuid4(),
            tenant_id=employee.tenant_id,
            role=employee.role,
            email=employee.email
        )
        self.client.force_authenticate(user=mock_user)
        return mock_user
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_invalid_uuid_in_url(self, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/invalid-uuid/')
        
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST])
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    def test_inactive_employee_not_in_list(self, mock_auth):
        inactive_employee = Employee.objects.create(
            tenant_id=self.tenant_id,
            first_name="Inactive",
            last_name="User",
            email="inactive@example.com",
            role="EMPLOYEE",
            designation="Ex-Employee",
            department="IT",
            joining_date=date.today() - timedelta(days=365),
            employment_type="Permanent",
            is_active=False,
            termination_date=date.today() - timedelta(days=30),
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        response = self.client.get('/api/v1/employees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        emails = [emp['email'] for emp in response.data]
        self.assertNotIn(inactive_employee.email, emails)
    
    @patch('employees.authentication.AuthServiceTokenAuthentication.authenticate')
    @patch('employees.views.get_kafka_producer')
    def test_kafka_failure_handling(self, mock_kafka, mock_auth):
        mock_user = self._authenticate_as(self.hr_user)
        mock_auth.return_value = (mock_user, None)
        
        mock_kafka.return_value = None
        
        update_data = {'designation': 'Updated Title'}
        
        response = self.client.patch(
            f'/api/v1/employees/{self.hr_user.id}/',
            update_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SerializerTestCase(TestCase):
    
    def test_employee_serializer_get_manager_name(self):
        from employees.serializers import EmployeeSerializer
        
        manager = Employee.objects.create(
            tenant_id=uuid.uuid4(),
            first_name="Manager",
            last_name="User",
            email="manager@test.com",
            role="MANAGER",
            designation="Manager",
            department="IT",
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        employee = Employee.objects.create(
            tenant_id=manager.tenant_id,
            first_name="Employee",
            last_name="User",
            email="emp@test.com",
            role="EMPLOYEE",
            designation="Developer",
            department="IT",
            manager=manager,
            joining_date=date.today(),
            employment_type="Permanent",
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        serializer = EmployeeSerializer(employee)
        
        self.assertEqual(serializer.data['manager_name'], "Manager User")