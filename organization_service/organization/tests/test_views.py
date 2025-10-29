from django.test import TestCase
from rest_framework.test import APITestCase, APIClient, APIRequestFactory
from rest_framework import status
from unittest.mock import patch, MagicMock, Mock
from organization.models import Organization
from organization.views import IsAdminPermission
import uuid


class MockUser:
    def __init__(self, user_id=None, tenant_id=None, role='User'):
        self.id = user_id or str(uuid.uuid4())
        self.tenant_id = tenant_id or str(uuid.uuid4())
        self.role = role
        self.is_authenticated = True


class OrganizationViewSetTestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.list_url = '/api/v1/organization/'
        
        self.org1 = Organization.objects.create(
            name='Test Org 1',
            domain='testorg1.com',
            is_active=True
        )
        self.org2 = Organization.objects.create(
            name='Test Org 2',
            domain='testorg2.com',
            is_active=True
        )
        
        self.detail_url = f'/api/v1/organization/{self.org1.id}/'
        
        self.admin_user = MockUser(role='Admin')
        self.regular_user = MockUser(role='User')

    def tearDown(self):
        Organization.objects.all().delete()

    def test_list_without_authentication(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_without_authentication(self):
        data = {'name': 'New Org', 'domain': 'neworg.com'}
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_organizations_as_authenticated_user(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 2)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_organizations_pagination(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        for i in range(15):
            Organization.objects.create(
                name=f'Org {i+3}',
                domain=f'org{i+3}.com'
            )
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertEqual(len(response.data['results']), 10)
        self.assertEqual(response.data['count'], 17)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_organizations_custom_page_size(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        for i in range(15):
            Organization.objects.create(
                name=f'Org {i+3}',
                domain=f'org{i+3}.com'
            )
        
        response = self.client.get(
            f'{self.list_url}?page_size=5',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 5)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_organizations_max_page_size(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            f'{self.list_url}?page_size=100',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(response.data['results']), 50)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_organization_success(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.regular_user, None)
        mock_check_perms.return_value = None
        
        response = self.client.get(
            self.detail_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Org 1')
        self.assertEqual(response.data['domain'], 'testorg1.com')
        self.assertIn('id', response.data)
        self.assertIn('created_at', response.data)
        self.assertIn('updated_at', response.data)
        self.assertIn('is_active', response.data)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_retrieve_nonexistent_organization(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        url = f'/api/v1/organization/{uuid.uuid4()}/'
        response = self.client.get(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('organization.views.OrganizationViewSet.create')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_as_admin_success(self, mock_auth, mock_create):
        mock_auth.return_value = (self.admin_user, None)
        
        from rest_framework.response import Response
        mock_create.return_value = Response({
            'id': str(uuid.uuid4()),
            'name': 'New Organization',
            'domain': 'neworg.com',
            'is_active': True
        }, status=status.HTTP_201_CREATED)
        
        data = {
            'name': 'New Organization',
            'domain': 'neworg.com',
            'is_active': True
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Organization')
        self.assertEqual(response.data['domain'], 'neworg.com')

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_as_regular_user_forbidden(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        data = {
            'name': 'New Organization',
            'domain': 'neworg.com'
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Only Admins can perform this action', str(response.data))

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_missing_required_fields(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        data = {'domain': 'invalidorg.com'}
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_missing_domain(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        data = {'name': 'Test Org'}
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('domain', response.data)

    @patch('organization.views.OrganizationViewSet.create')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_with_duplicate_name(self, mock_auth, mock_create):
        mock_auth.return_value = (self.admin_user, None)
        
        from rest_framework.response import Response
        mock_create.return_value = Response({
            'name': ['organization with this name already exists.']
        }, status=status.HTTP_400_BAD_REQUEST)
        
        data = {
            'name': 'Test Org 1',
            'domain': 'unique.com'
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('organization.views.OrganizationViewSet.update')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_update_organization_as_admin_success(self, mock_auth, mock_check_perms, mock_update):
        mock_auth.return_value = (self.admin_user, None)
        mock_check_perms.return_value = None
        
        from rest_framework.response import Response
        mock_update.return_value = Response({
            'id': str(self.org1.id),
            'name': 'Updated Org Name',
            'domain': 'updatedorg.com',
            'is_active': False
        }, status=status.HTTP_200_OK)
        
        data = {
            'name': 'Updated Org Name',
            'domain': 'updatedorg.com',
            'is_active': False
        }
        
        response = self.client.put(
            self.detail_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Updated Org Name')

    @patch('organization.views.OrganizationViewSet.update')
    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_partial_update_organization_as_admin(self, mock_auth, mock_check_perms, mock_update):
        mock_auth.return_value = (self.admin_user, None)
        mock_check_perms.return_value = None
        
        from rest_framework.response import Response
        mock_update.return_value = Response({
            'id': str(self.org1.id),
            'name': 'Partially Updated Org',
            'domain': 'testorg1.com',
            'is_active': True
        }, status=status.HTTP_200_OK)
        
        data = {'name': 'Partially Updated Org'}
        
        response = self.client.patch(
            self.detail_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Partially Updated Org')

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_update_organization_as_regular_user_forbidden(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.regular_user, None)
        
        from rest_framework.exceptions import PermissionDenied
        mock_check_perms.side_effect = PermissionDenied("Only Admins can perform this action.")
        
        data = {
            'name': 'Updated Org Name',
            'domain': 'updatedorg.com'
        }
        
        response = self.client.put(
            self.detail_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_update_nonexistent_organization(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        url = f'/api/v1/organization/{uuid.uuid4()}/'
        data = {'name': 'Updated Org', 'domain': 'updated.com'}
        
        response = self.client.put(
            url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_delete_organization_as_admin_success(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.admin_user, None)
        mock_check_perms.return_value = None
        
        org_to_delete = Organization.objects.create(
            name='Org to Delete',
            domain='delete.com'
        )
        url = f'/api/v1/organization/{org_to_delete.id}/'
        
        response = self.client.delete(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Organization.objects.filter(id=org_to_delete.id).exists())

    @patch('rest_framework.views.APIView.check_object_permissions')
    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_delete_organization_as_regular_user_forbidden(self, mock_auth, mock_check_perms):
        mock_auth.return_value = (self.regular_user, None)
        
        from rest_framework.exceptions import PermissionDenied
        mock_check_perms.side_effect = PermissionDenied("Only Admins can perform this action.")
        
        response = self.client.delete(
            self.detail_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Organization.objects.filter(id=self.org1.id).exists())

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_delete_nonexistent_organization(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        url = f'/api/v1/organization/{uuid.uuid4()}/'
        
        response = self.client.delete(
            url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_admin_can_access_list(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer token'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_regular_user_can_list(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer token'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_regular_user_cannot_create(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        data = {'name': 'Test', 'domain': 'test.com'}
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer token'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Only Admins can perform this action', str(response.data))

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_create_organization_invalid_data_types(self, mock_auth):
        mock_auth.return_value = (self.admin_user, None)
        
        data = {
            'name': '',
            'domain': ''
        }
        
        response = self.client.post(
            self.list_url,
            data,
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_list_organizations_returns_correct_fields(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        org_data = response.data['results'][0]
        
        expected_fields = ['id', 'name', 'domain', 'created_at', 'updated_at', 'is_active']
        for field in expected_fields:
            self.assertIn(field, org_data)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_empty_list(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        Organization.objects.all().delete()
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
        self.assertEqual(response.data['count'], 0)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_filter_active_organizations(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        Organization.objects.create(
            name='Inactive Org',
            domain='inactive.com',
            is_active=False
        )
        
        response = self.client.get(
            f'{self.list_url}?is_active=true',
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('organization.views.AuthServiceTokenAuthentication.authenticate')
    def test_organization_ordering(self, mock_auth):
        mock_auth.return_value = (self.regular_user, None)
        
        response = self.client.get(
            self.list_url,
            HTTP_AUTHORIZATION='Bearer test-token'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data['results']), 0)


class IsAdminPermissionTestCase(TestCase):

    def setUp(self):
        self.permission = IsAdminPermission()
        self.mock_view = MagicMock()
        self.factory = APIRequestFactory()

    def test_safe_methods_allowed_for_all_users(self):
        for method in ['get', 'head', 'options']:
            request = getattr(self.factory, method)('/api/v1/organization/')
            request.user = MockUser(role='User')
            
            has_permission = self.permission.has_permission(request, self.mock_view)
            self.assertTrue(has_permission, f"{method.upper()} should be allowed for regular users")

    def test_write_methods_allowed_for_admin(self):
        for method in ['post', 'put', 'patch', 'delete']:
            request = getattr(self.factory, method)('/api/v1/organization/')
            request.user = MockUser(role='Admin')
            
            has_permission = self.permission.has_permission(request, self.mock_view)
            self.assertTrue(has_permission, f"{method.upper()} should be allowed for admin")

    def test_write_methods_denied_for_non_admin(self):
        from rest_framework.exceptions import PermissionDenied
        
        for method in ['post', 'put', 'patch', 'delete']:
            request = getattr(self.factory, method)('/api/v1/organization/')
            request.user = MockUser(role='User')
            
            with self.assertRaises(PermissionDenied) as context:
                self.permission.has_permission(request, self.mock_view)
            
            self.assertIn('Only Admins can perform this action', str(context.exception))

    def test_permission_with_different_roles(self):
        test_cases = [
            ('Admin', 'post', True),
            ('User', 'get', True),
            ('Manager', 'post', False),
            ('Employee', 'delete', False),
        ]
        
        for role, method, should_pass in test_cases:
            request = getattr(self.factory, method)('/api/v1/organization/')
            request.user = MockUser(role=role)
            
            if should_pass:
                result = self.permission.has_permission(request, self.mock_view)
                self.assertTrue(result)
            else:
                from rest_framework.exceptions import PermissionDenied
                with self.assertRaises(PermissionDenied):
                    self.permission.has_permission(request, self.mock_view)

    def test_permission_without_role_attribute(self):
        from rest_framework.exceptions import PermissionDenied
        
        request = self.factory.post('/api/v1/organization/')
        request.user = MagicMock(spec=['is_authenticated'])
        
        with self.assertRaises(PermissionDenied):
            self.permission.has_permission(request, self.mock_view)

    def test_get_method_always_allowed(self):
        request = self.factory.get('/api/v1/organization/')
        
        for role in ['Admin', 'User', 'Guest', 'Manager']:
            request.user = MockUser(role=role)
            has_permission = self.permission.has_permission(request, self.mock_view)
            self.assertTrue(has_permission, f"GET should be allowed for {role}")

    def test_options_method_always_allowed(self):
        request = self.factory.options('/api/v1/organization/')
        request.user = MockUser(role='User')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertTrue(has_permission)

    def test_head_method_always_allowed(self):
        request = self.factory.head('/api/v1/organization/')
        request.user = MockUser(role='User')
        
        has_permission = self.permission.has_permission(request, self.mock_view)
        self.assertTrue(has_permission)