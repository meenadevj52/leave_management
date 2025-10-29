from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
from accounts.models import User
import uuid


class RegisterViewTestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('signup')
        self.valid_tenant_id = str(uuid.uuid4())
        
        self.valid_payload = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'first_name': 'Test',
            'last_name': 'User',
            'tenant_id': self.valid_tenant_id,
            'role': 'employee'
        }

    @patch('accounts.views.send_tenant_verification_request')
    def test_successful_registration(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        response = self.client.post(
            self.register_url,
            self.valid_payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='test@example.com').exists())
        
        mock_tenant_verification.assert_called_once_with(self.valid_tenant_id)
        
        user = User.objects.get(email='test@example.com')
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.first_name, 'Test')
        self.assertEqual(user.tenant_id, uuid.UUID(self.valid_tenant_id))

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_with_invalid_tenant(self, mock_tenant_verification):
        mock_tenant_verification.return_value = False
        
        response = self.client.post(
            self.register_url,
            self.valid_payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tenant_id', str(response.data))
        self.assertFalse(User.objects.filter(email='test@example.com').exists())

    def test_registration_without_tenant_id(self):
        payload = self.valid_payload.copy()
        payload.pop('tenant_id')
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tenant_id', str(response.data))

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_password_mismatch(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        payload = self.valid_payload.copy()
        payload['password2'] = 'DifferentPass123!'
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', str(response.data))

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_weak_password(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        payload = self.valid_payload.copy()
        payload['password'] = '123'
        payload['password2'] = '123'
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_duplicate_email(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        self.client.post(self.register_url, self.valid_payload, format='json')
        
        response = self.client.post(
            self.register_url,
            self.valid_payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_duplicate_username(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        self.client.post(self.register_url, self.valid_payload, format='json')
        
        payload = self.valid_payload.copy()
        payload['email'] = 'different@example.com'
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_invalid_email(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        payload = self.valid_payload.copy()
        payload['email'] = 'invalid-email'
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', str(response.data))

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_missing_required_fields(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        required_fields = ['username', 'email', 'password', 'password2']
        
        for field in required_fields:
            payload = self.valid_payload.copy()
            payload.pop(field)
            
            response = self.client.post(
                self.register_url,
                payload,
                format='json'
            )
            
            self.assertEqual(
                response.status_code, 
                status.HTTP_400_BAD_REQUEST,
                f"Should fail when {field} is missing"
            )

    @patch('accounts.views.send_tenant_verification_request')
    def test_registration_invalid_tenant_id_format(self, mock_tenant_verification):
        mock_tenant_verification.return_value = True
        
        payload = self.valid_payload.copy()
        payload['tenant_id'] = 'invalid-uuid'
        
        response = self.client.post(
            self.register_url,
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginViewTestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.login_url = reverse('signin')
        self.tenant_id = uuid.uuid4()
        
        self.test_user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            tenant_id=self.tenant_id,
            role='employee'
        )
        
        self.valid_credentials = {
            'email': 'test@example.com',
            'password': 'TestPass123!'
        }

    def test_successful_login(self):
        response = self.client.post(
            self.login_url,
            self.valid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['message'], 'Login successful')
        
        self.assertIn('token', response.data)
        self.assertIn('access', response.data['token'])
        self.assertIn('refresh', response.data['token'])
        
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], 'test@example.com')
        self.assertEqual(response.data['user']['username'], 'testuser')

    def test_login_invalid_password(self):
        invalid_credentials = {
            'email': 'test@example.com',
            'password': 'WrongPassword123!'
        }
        
        response = self.client.post(
            self.login_url,
            invalid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['message'], 'Invalid credentials')
        self.assertNotIn('token', response.data)

    def test_login_invalid_email(self):
        invalid_credentials = {
            'email': 'nonexistent@example.com',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(
            self.login_url,
            invalid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['message'], 'Invalid credentials')

    def test_login_missing_email(self):
        incomplete_credentials = {
            'password': 'TestPass123!'
        }
        
        response = self.client.post(
            self.login_url,
            incomplete_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', str(response.data))

    def test_login_missing_password(self):
        incomplete_credentials = {
            'email': 'test@example.com'
        }
        
        response = self.client.post(
            self.login_url,
            incomplete_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', str(response.data))

    def test_login_empty_credentials(self):
        response = self.client.post(
            self.login_url,
            {},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_invalid_email_format(self):
        invalid_credentials = {
            'email': 'not-an-email',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(
            self.login_url,
            invalid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', str(response.data))

    def test_login_returns_correct_user_data(self):
        response = self.client.post(
            self.login_url,
            self.valid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        user_data = response.data['user']
        self.assertEqual(user_data['email'], self.test_user.email)
        self.assertEqual(user_data['username'], self.test_user.username)
        self.assertEqual(user_data['first_name'], self.test_user.first_name)
        self.assertEqual(user_data['last_name'], self.test_user.last_name)
        self.assertEqual(user_data['tenant_id'], str(self.test_user.tenant_id))

    def test_jwt_token_validity(self):
        response = self.client.post(
            self.login_url,
            self.valid_credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        access_token = response.data['token']['access']
        refresh_token = response.data['token']['refresh']
        
        self.assertTrue(len(access_token) > 0)
        self.assertTrue(len(refresh_token) > 0)
        
        self.assertNotEqual(access_token, refresh_token)

    def test_login_case_sensitive_email(self):
        credentials = {
            'email': 'TEST@example.com',
            'password': 'TestPass123!'
        }
        
        response = self.client.post(
            self.login_url,
            credentials,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_multiple_successful_logins(self):
        response1 = self.client.post(
            self.login_url,
            self.valid_credentials,
            format='json'
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        response2 = self.client.post(
            self.login_url,
            self.valid_credentials,
            format='json'
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        self.assertNotEqual(
            response1.data['token']['access'],
            response2.data['token']['access']
        )