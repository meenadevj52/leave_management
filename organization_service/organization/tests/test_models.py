from django.test import TestCase
from django.db import IntegrityError
from organization.models import Organization
from datetime import datetime
from django.utils import timezone

class OrganizationModelTest(TestCase):
    def setUp(self):
        self.org_data = {
            'name': 'Test Organization',
            'domain': 'test.com',
        }
        self.organization = Organization.objects.create(**self.org_data)

    def test_organization_creation(self):
        self.assertTrue(isinstance(self.organization, Organization))
        self.assertEqual(self.organization.name, self.org_data['name'])
        self.assertEqual(self.organization.domain, self.org_data['domain'])
        self.assertTrue(self.organization.is_active)
        self.assertIsNotNone(self.organization.id)

    def test_organization_str_representation(self):
        self.assertEqual(str(self.organization), self.org_data['name'])

    def test_unique_name_constraint(self):
        with self.assertRaises(IntegrityError):
            Organization.objects.create(
                name=self.org_data['name'],
                domain='another-domain.com'
            )

    def test_unique_domain_constraint(self):
        with self.assertRaises(IntegrityError):
            Organization.objects.create(
                name='Another Organization',
                domain=self.org_data['domain']
            )

    def test_auto_timestamp_fields(self):
        self.assertIsInstance(self.organization.created_at, datetime)
        self.assertIsInstance(self.organization.updated_at, datetime)
        
        import time
        old_updated_at = self.organization.updated_at
        time.sleep(0.1)
        
        self.organization.name = 'Updated Name'
        self.organization.save()
        
        self.organization.refresh_from_db()
        self.assertGreater(self.organization.updated_at, old_updated_at)

    def test_default_is_active(self):
        new_org = Organization.objects.create(
            name='Another Org',
            domain='another.com'
        )
        self.assertTrue(new_org.is_active)

    def test_fields_max_length(self):
        from django.core.exceptions import ValidationError
        
        org = Organization.objects.create(
            name='A' * 255,
            domain='B' * 255
        )
        self.assertEqual(len(org.name), 255)
        self.assertEqual(len(org.domain), 255)

        org_invalid = Organization(
            name='A' * 256,
            domain='domain.com'
        )
        
        with self.assertRaises(ValidationError):
            org_invalid.full_clean()