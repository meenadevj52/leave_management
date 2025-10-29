import uuid
from django.test import TestCase
from django.db import IntegrityError
from accounts.models import User


class UserModelTest(TestCase):

    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.user_data = {
            'username': 'testuser',
            'email': 'testuser@example.com',
            'password': 'testpass123',
            'tenant_id': self.tenant_id,
            'phone_number': '1234567890',
            'role': 'employee'
        }

    def test_create_user_with_all_fields(self):
        user = User.objects.create_user(**self.user_data)
        
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.email, 'testuser@example.com')
        self.assertEqual(user.tenant_id, self.tenant_id)
        self.assertEqual(user.phone_number, '1234567890')
        self.assertEqual(user.role, 'employee')
        self.assertTrue(user.check_password('testpass123'))

    def test_user_uuid_auto_generated(self):
        user = User.objects.create_user(**self.user_data)
        
        self.assertIsNotNone(user.user_uuid)
        self.assertIsInstance(user.user_uuid, uuid.UUID)

    def test_user_uuid_is_unique(self):
        user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='pass123',
            tenant_id=self.tenant_id
        )
        user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='pass123',
            tenant_id=self.tenant_id
        )
        
        self.assertNotEqual(user1.user_uuid, user2.user_uuid)

    def test_email_is_unique(self):
        User.objects.create_user(**self.user_data)
        
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='anotheruser',
                email='testuser@example.com',
                password='pass123',
                tenant_id=self.tenant_id
            )

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, 'email')

    def test_user_str_method(self):
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(str(user), 'testuser@example.com')

    def test_create_user_with_optional_fields_blank(self):
        user = User.objects.create_user(
            username='minimaluser',
            email='minimal@example.com',
            password='pass123',
            tenant_id=self.tenant_id
        )
        
        self.assertIsNone(user.phone_number)
        self.assertIsNone(user.role)

    def test_phone_number_max_length(self):
        max_length = User._meta.get_field('phone_number').max_length
        self.assertEqual(max_length, 20)

    def test_role_max_length(self):
        max_length = User._meta.get_field('role').max_length
        self.assertEqual(max_length, 50)

    def test_tenant_id_not_editable(self):
        field = User._meta.get_field('tenant_id')
        self.assertFalse(field.editable)

    def test_user_uuid_not_editable(self):
        field = User._meta.get_field('user_uuid')
        self.assertFalse(field.editable)

    def test_create_superuser(self):
        admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',
            tenant_id=self.tenant_id
        )
        
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_staff)
        self.assertEqual(admin_user.email, 'admin@example.com')