import uuid
import json
from io import BytesIO
from unittest.mock import patch, MagicMock, Mock
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from policies.models import Policy, PolicyAudit


class MockUser:
    def __init__(self, user_id=None, tenant_id=None, role='HR'):
        self.id = user_id or str(uuid.uuid4())
        self.tenant_id = tenant_id or str(uuid.uuid4())
        self.role = role
        self.username = f"user_{role}"
        self.is_authenticated = True


class PolicyViewSetTestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.list_url = '/api/v1/policy/'
        
        self.tenant_id = uuid.uuid4()
        self.hr_user = MockUser(role='HR', tenant_id=self.tenant_id)
        self.admin_user = MockUser(role='ADMIN', tenant_id=self.tenant_id)
        self.chro_user = MockUser(role='CHRO', tenant_id=self.tenant_id)
        self.regular_user = MockUser(role='Employee', tenant_id=self.tenant_id)
        
        self.policy1 = Policy.objects.create(
            tenant_id=self.tenant_id,
            policy_name='Annual Leave Policy',
            policy_type='Annual',
            description='Standard annual leave policy',
            major_version=1,
            minor_version=0,
            status='ACTIVE',
            is_active=True,
            approval_route=['HR', 'CHRO'],
            entitlement={'base_days': 20},
            carry_forward=5,
            encashment=10,
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.policy2 = Policy.objects.create(
            tenant_id=self.tenant_id,
            policy_name='Sick Leave Policy',
            policy_type='Sick',
            description='Sick leave policy',
            major_version=1,
            minor_version=0,
            status='PENDING_APPROVAL',
            is_active=False,
            current_approval_step=0,
            approval_route=['HR', 'CHRO'],
            entitlement={'base_days': 10},
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.other_tenant_id = uuid.uuid4()
        self.other_policy = Policy.objects.create(
            tenant_id=self.other_tenant_id,
            policy_name='Other Tenant Policy',
            policy_type='Annual',
            status='ACTIVE',
            is_active=True,
            approval_route=['HR'],
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        self.detail_url = f'/api/v1/policy/{self.policy1.id}/'

    def tearDown(self):
        Policy.objects.all().delete()
        PolicyAudit.objects.all().delete()

    def test_list_without_authentication(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_without_authentication(self):
        data = {'policy_name': 'New Policy', 'policy_type': 'Casual'}
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_non_hr_admin_cannot_access(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_policies_as_hr(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 2)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_tenant_isolation(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        policy_ids = [p['id'] for p in response.data]
        
        self.assertIn(str(self.policy1.id), policy_ids)
        self.assertIn(str(self.policy2.id), policy_ids)
        self.assertNotIn(str(self.other_policy.id), policy_ids)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_policy_success(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        response = self.client.get(
            self.detail_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['policy_name'], 'Annual Leave Policy')
        self.assertEqual(response.data['policy_type'], 'Annual')
        self.assertEqual(response.data['status'], 'ACTIVE')
        self.assertIn('approval_route', response.data)
        self.assertIn('conditions', response.data)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_nonexistent_policy(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        url = f'/api/v1/policy/{uuid.uuid4()}/'
        response = self.client.get(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('policies.views.send_policy_event')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_success(self, mock_auth, mock_send_event):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Casual Leave Policy',
            'policy_type': 'Casual',
            'description': 'Casual leave policy',
            'approval_route': ['HR', 'CHRO'],
            'entitlement': {'base_days': 12},
            'carry_forward': 3,
            'encashment': 5,
            'notice_period': 1,
            'limit_per_month': 2
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['policy_name'], 'Casual Leave Policy')
        self.assertEqual(response.data['status'], 'PENDING_APPROVAL')
        self.assertEqual(response.data['major_version'], 1)
        self.assertEqual(response.data['minor_version'], 0)
        self.assertFalse(response.data['is_active'])
        
        policy_id = response.data['id']
        audit = PolicyAudit.objects.filter(
            policy_id=policy_id,
            update_type='CREATE'
        ).first()
        self.assertIsNotNone(audit)
        
        mock_send_event.assert_called_once()

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_missing_required_fields(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {'description': 'Missing name and type'}
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_empty_approval_route(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Test Policy',
            'policy_type': 'Annual',
            'approval_route': []
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('approval_route', str(response.data))

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_invalid_conditions(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Test Policy',
            'policy_type': 'Annual',
            'approval_route': ['HR'],
            'conditions': [
                {'description': 'Missing id and checks'}
            ]
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'                        
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_both_priorities_true(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Test Policy',
            'policy_type': 'Annual',
            'approval_route': ['HR'],
            'carry_forward_priority': True,
            'encashment_priority': True
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_custom_employment_duration_validation(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Test Policy',
            'policy_type': 'Annual',
            'approval_route': ['HR'],
            'employment_duration': 'CUSTOM',
            'employment_duration_custom_days': 0
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('policies.views.send_policy_event')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_version_increment(self, mock_auth, mock_send_event):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Annual Leave Policy v2',
            'policy_type': 'Annual',
            'approval_route': ['HR', 'CHRO'],
            'entitlement': {'base_days': 25}
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['major_version'], 1)
        self.assertEqual(response.data['minor_version'], 1)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_update_policy_creates_new_version(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        original_id = self.policy1.id
        
        data = {
            'policy_name': 'Updated Annual Leave Policy',
            'policy_type': 'Annual',
            'approval_route': ['HR', 'CHRO'],
            'entitlement': {'base_days': 25},
            'change_description': 'Increased base days'
        }
        
        response = self.client.put(
            self.detail_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        old_policy = Policy.objects.get(id=original_id)
        self.assertEqual(old_policy.status, 'SUPERSEDED')
        self.assertFalse(old_policy.is_active)
        
        new_policy_id = response.data['id']
        self.assertNotEqual(str(original_id), new_policy_id)
        
        new_policy = Policy.objects.get(id=new_policy_id)
        self.assertEqual(new_policy.status, 'PENDING_APPROVAL')
        self.assertEqual(new_policy.minor_version, 1)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_partial_update_policy(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        data = {'carry_forward': 10}
        
        response = self.client.patch(
            self.detail_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['carry_forward'], 10)

    @patch('policies.views.send_policy_event')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_approve_policy_first_step(self, mock_auth, mock_check_perms, mock_send_event):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy2.id}/approve/'
        
        response = self.client.post(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['current_step'], 1)
        self.assertEqual(response.data['total_steps'], 2)
        
        self.policy2.refresh_from_db()
        self.assertEqual(self.policy2.status, 'PENDING_APPROVAL')
        self.assertEqual(self.policy2.current_approval_step, 1)

    @patch('policies.views.send_policy_event')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_approve_policy_final_step(self, mock_auth, mock_check_perms, mock_send_event):
        pending_annual_policy = Policy.objects.create(
            tenant_id=self.tenant_id,
            policy_name='Annual Leave Policy v2',
            policy_type='Annual',
            major_version=1,
            minor_version=1,
            status='PENDING_APPROVAL',
            is_active=False,
            current_approval_step=1,
            approval_route=['HR', 'CHRO'],
            entitlement={'base_days': 25},
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        mock_auth.return_value = (self.chro_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{pending_annual_policy.id}/approve/'
        
        response = self.client.post(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        pending_annual_policy.refresh_from_db()
        self.assertEqual(pending_annual_policy.status, 'ACTIVE')
        self.assertTrue(pending_annual_policy.is_active)
        
        self.policy1.refresh_from_db()
        self.assertEqual(self.policy1.status, 'SUPERSEDED')
        self.assertFalse(self.policy1.is_active)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_approve_wrong_role(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.chro_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy2.id}/approve/'
        
        response = self.client.post(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_approve_already_approved_policy(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/approve/'
        
        response = self.client.post(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('policies.views.send_policy_event')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_reject_policy_success(self, mock_auth, mock_check_perms, mock_send_event):
        mock_auth.return_value = (self.chro_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy2.id}/reject/'
        data = {
            'reason': 'Policy does not meet requirements',
            'comment': 'Please revise and resubmit'
        }
        
        response = self.client.post(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'rejected')
        
        self.policy2.refresh_from_db()
        self.assertEqual(self.policy2.status, 'REJECTED')
        self.assertFalse(self.policy2.is_active)
        
        audit = PolicyAudit.objects.filter(
            policy=self.policy2,
            update_type='REJECT'
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.reason, 'Policy does not meet requirements')

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_reject_policy_wrong_role(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.regular_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy2.id}/reject/'
        data = {'reason': 'Test rejection'}
        
        response = self.client.post(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_reject_active_policy_fails(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/reject/'
        data = {'reason': 'Test'}
        
        response = self.client.post(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_test_validation_success(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/test-validation/'
        
        data = {
            'leave_request': {
                'leave_type': 'Annual',
                'leave_days': 5,
                'request_type': 'leave'
            },
            'employee': {
                'role': 'Employee',
                'tenure_years': 2,
                'manager_id': str(uuid.uuid4())
            },
            'context': {
                'accrual_balance': 10
            }
        }
        
        response = self.client.post(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('is_valid', response.data)
        self.assertIn('errors', response.data)
        self.assertIn('actions_to_execute', response.data)
        self.assertIn('approval_chain', response.data)
        self.assertIn('policy', response.data)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_test_validation_with_errors(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/test-validation/'
        
        data = {
            'leave_request': {
                'leave_type': 'Annual',
                'leave_days': 15,
                'request_type': 'leave'
            },
            'employee': {
                'role': 'Employee',
                'tenure_years': 1
            },
            'context': {
                'accrual_balance': 5
            }
        }
        
        response = self.client.post(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_valid'])
        self.assertGreater(len(response.data['errors']), 0)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_audit_history_success(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        PolicyAudit.objects.create(
            policy=self.policy1,
            update_type='CREATE',
            initiator_id=uuid.uuid4()
        )
        PolicyAudit.objects.create(
            policy=self.policy1,
            update_type='APPROVE',
            initiator_id=uuid.uuid4()
        )
        
        url = f'/api/v1/policy/{self.policy1.id}/audit-history/'
        
        response = self.client.get(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 2)

    @patch('django.core.files.storage.default_storage.save')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_upload_attachment_success(self, mock_auth, mock_check_perms, mock_storage_save):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        mock_storage_save.return_value = 'policy_attachments/test.pdf'
        
        url = f'/api/v1/policy/{self.policy1.id}/upload-attachment/'
        
        file_content = b'Test PDF content'
        test_file = SimpleUploadedFile(
            'test_document.pdf',
            file_content,
            content_type='application/pdf'
        )
        
        data = {'file': test_file}
        
        response = self.client.post(
            url,
            data,
            format='multipart',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('attachment', response.data)
        
        self.policy1.refresh_from_db()
        self.assertGreater(len(self.policy1.attachments), 0)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_upload_attachment_no_file(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/upload-attachment/'
        
        response = self.client.post(
            url,
            {},
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_upload_attachment_file_too_large(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/upload-attachment/'
        
        large_file = SimpleUploadedFile(
            'large_file.pdf',
            b'x' * (11 * 1024 * 1024),
            content_type='application/pdf'
        )
        
        data = {'file': large_file}
        
        response = self.client.post(
            url,
            data,
            format='multipart',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('10MB', str(response.data))

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_upload_attachment_invalid_type(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/upload-attachment/'
        
        invalid_file = SimpleUploadedFile(
            'script.exe',
            b'malicious content',
            content_type='application/exe'
        )
        
        data = {'file': invalid_file}
        
        response = self.client.post(
            url,
            data,
            format='multipart',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not allowed', str(response.data))

    @patch('policies.views.send_policy_event')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_delete_inactive_policy_success(self, mock_auth, mock_check_perms, mock_send_event):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy2.id}/'
        
        response = self.client.delete(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        self.policy2.refresh_from_db()
        self.assertEqual(self.policy2.status, 'INACTIVE')
        self.assertFalse(self.policy2.is_active)
        
        audit = PolicyAudit.objects.filter(
            policy=self.policy2,
            update_type='DELETE'
        ).first()
        self.assertIsNotNone(audit)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_delete_active_policy_fails(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.hr_user, None)
        mock_check_perms.return_value = None
        
        url = f'/api/v1/policy/{self.policy1.id}/'
        
        response = self.client.delete(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot delete an active policy', str(response.data))

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_policies_empty_queryset(self, mock_auth):
        new_tenant_user = MockUser(role='HR', tenant_id=uuid.uuid4())
        mock_auth.return_value = (new_tenant_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_queryset_filters_by_tenant(self, mock_auth):
        mock_auth.return_value = (self.hr_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        for policy in response.data:
            self.assertEqual(policy['tenant_id'], str(self.tenant_id))

    @patch('policies.views.send_policy_event')
    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_policy_sets_correct_defaults(self, mock_auth, mock_send_event):
        mock_auth.return_value = (self.hr_user, None)
        
        data = {
            'policy_name': 'Test Policy',
            'policy_type': 'Test',
            'approval_route': ['HR']
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'PENDING_APPROVAL')
        self.assertFalse(response.data['is_active'])
        self.assertEqual(response.data['current_approval_step'], 0)
        self.assertEqual(response.data['tenant_id'], str(self.tenant_id))

    @patch('policies.views.AuthServiceTokenAuthentication.authenticate')
    def test_user_without_tenant_gets_empty_queryset(self, mock_auth):
        user_no_tenant = MockUser(role='HR', tenant_id=None)
        mock_auth.return_value = (user_no_tenant, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


class IsHROrAdminPermissionTestCase(TestCase):

    def setUp(self):
        from policies.permissions import IsHROrAdmin
        from rest_framework.test import APIRequestFactory
        
        self.permission = IsHROrAdmin()
        self.factory = APIRequestFactory()
        self.mock_view = MagicMock()

    def test_hr_role_has_permission(self):
        request = self.factory.get('/api/v1/policy/')
        request.user = MockUser(role='HR')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertTrue(has_permission)

    def test_admin_role_has_permission(self):
        request = self.factory.get('/api/v1/policy/')
        request.user = MockUser(role='ADMIN')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertTrue(has_permission)

    def test_chro_role_has_permission(self):
        request = self.factory.get('/api/v1/policy/')
        request.user = MockUser(role='CHRO')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertTrue(has_permission)

    def test_other_roles_denied(self):
        for role in ['Employee', 'Manager', 'User']:
            request = self.factory.get('/api/v1/policy/')
            request.user = MockUser(role=role)
            
            has_permission = self.permission.has_permission(request, self.mock_view)
            self.assertFalse(has_permission, f"Role {role} should be denied")

    def test_unauthenticated_user_denied(self):
        request = self.factory.get('/api/v1/policy/')
        request.user = MagicMock(is_authenticated=False)
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertFalse(has_permission)

    def test_no_user_attribute_denied(self):
        request = self.factory.get('/api/v1/policy/')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertFalse(has_permission)


class HelperFunctionsTestCase(TestCase):

    def test_to_uuid_with_uuid(self):
        from policies.views import to_uuid
        
        test_uuid = uuid.uuid4()
        result = to_uuid(test_uuid)
        
        self.assertEqual(result, test_uuid)
        self.assertIsInstance(result, uuid.UUID)

    def test_to_uuid_with_string(self):
        from policies.views import to_uuid
        
        test_uuid = uuid.uuid4()
        result = to_uuid(str(test_uuid))
        
        self.assertEqual(result, test_uuid)
        self.assertIsInstance(result, uuid.UUID)

    def test_to_uuid_with_none(self):
        from policies.views import to_uuid
        
        result = to_uuid(None)
        self.assertIsNone(result)

    def test_to_uuid_with_invalid_string(self):
        from policies.views import to_uuid
        
        result = to_uuid('invalid-uuid')
        self.assertIsNone(result)

    def test_clean_policy_data(self):
        from policies.views import clean_policy_data
        
        policy = Policy.objects.create(
            tenant_id=uuid.uuid4(),
            policy_name='Test Policy',
            policy_type='Test',
            approval_route=['HR'],
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        cleaned_data = clean_policy_data(policy)
        
        self.assertIsInstance(cleaned_data, dict)
        self.assertIn('id', cleaned_data)
        self.assertIn('policy_name', cleaned_data)
        self.assertIn('policy_type', cleaned_data)
        self.assertIsInstance(cleaned_data['id'], str)
        self.assertIsInstance(cleaned_data['tenant_id'], str)

    def test_to_uuid_with_uuid(self):
        from policies.views import to_uuid
        
        test_uuid = uuid.uuid4()
        result = to_uuid(test_uuid)
        
        self.assertEqual(result, test_uuid)
        self.assertIsInstance(result, uuid.UUID)

    def test_to_uuid_with_string(self):
        from policies.views import to_uuid
        
        test_uuid = uuid.uuid4()
        result = to_uuid(str(test_uuid))
        
        self.assertEqual(result, test_uuid)
        self.assertIsInstance(result, uuid.UUID)

    def test_to_uuid_with_none(self):
        from policies.views import to_uuid
        
        result = to_uuid(None)
        self.assertIsNone(result)

    def test_to_uuid_with_invalid_string(self):
        from policies.views import to_uuid
        
        result = to_uuid('invalid-uuid')
        self.assertIsNone(result)

    def test_clean_policy_data(self):
        from policies.views import clean_policy_data
        
        policy = Policy.objects.create(
            tenant_id=uuid.uuid4(),
            policy_name='Test Policy',
            policy_type='Test',
            approval_route=['HR'],
            created_by=uuid.uuid4(),
            updated_by=uuid.uuid4()
        )
        
        cleaned_data = clean_policy_data(policy)
        
        self.assertIsInstance(cleaned_data, dict)
        self.assertIn('id', cleaned_data)
        self.assertIn('policy_name', cleaned_data)
        self.assertIn('policy_type', cleaned_data)
        self.assertIsInstance(cleaned_data['id'], str)
        self.assertIsInstance(cleaned_data['tenant_id'], str)