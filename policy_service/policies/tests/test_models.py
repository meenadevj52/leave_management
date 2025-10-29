import uuid
from datetime import datetime
from django.test import TestCase
from django.utils import timezone
from django.db import IntegrityError
from policies.models import Policy, PolicyAudit, get_default_conditions


class PolicyModelTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.default_policy_data = {
            'tenant_id': self.tenant_id,
            'policy_name': 'Annual Leave Policy',
            'policy_type': 'ANNUAL',
            'description': 'Standard annual leave policy',
            'created_by': self.user_id,
            'updated_by': self.user_id,
        }

    def test_policy_creation(self):
        """Test creating a new policy with default values"""
        policy = Policy.objects.create(**self.default_policy_data)
        
        self.assertIsNotNone(policy.id)
        self.assertEqual(policy.major_version, 1)
        self.assertEqual(policy.minor_version, 0)
        self.assertEqual(policy.version, 'v1.0')
        self.assertEqual(policy.status, 'PENDING_APPROVAL')
        self.assertFalse(policy.is_active)

    def test_policy_unique_constraint(self):
        """Test unique constraint on tenant_id, policy_type, and version numbers"""
        Policy.objects.create(**self.default_policy_data)
        
        with self.assertRaises(IntegrityError):
            Policy.objects.create(**self.default_policy_data)

    def test_policy_version_generation(self):
        """Test automatic version string generation"""
        policy = Policy.objects.create(**self.default_policy_data)
        self.assertEqual(policy.version, 'v1.0')
        
        policy.major_version = 2
        policy.minor_version = 1
        policy.save()
        self.assertEqual(policy.version, 'v2.1')

    def test_default_conditions(self):
        """Test that default conditions are properly set"""
        policy = Policy.objects.create(**self.default_policy_data)
        self.assertEqual(policy.conditions, get_default_conditions())
        self.assertTrue(isinstance(policy.conditions, list))
        self.assertTrue(len(policy.conditions) > 0)

    def test_policy_string_representation(self):
        """Test the string representation of the Policy model"""
        policy = Policy.objects.create(**self.default_policy_data)
        expected_str = f"Annual Leave Policy (ANNUAL) - v1.0"
        self.assertEqual(str(policy), expected_str)

    def test_policy_indexes(self):
        """Test that indexes are properly created"""
        policy = Policy.objects.create(**self.default_policy_data)
        
        self.assertIsNotNone(Policy.objects.filter(tenant_id=self.tenant_id).first())
        self.assertIsNotNone(Policy.objects.filter(status='PENDING_APPROVAL').first())
        self.assertIsNotNone(Policy.objects.filter(
            tenant_id=self.tenant_id,
            policy_type='ANNUAL',
            is_active=False
        ).first())

    def test_policy_json_fields(self):
        """Test JSON fields default values and updates"""
        policy = Policy.objects.create(**self.default_policy_data)
        
        self.assertEqual(policy.attachments, [])
        self.assertEqual(policy.applies_to, [])
        self.assertEqual(policy.excludes, [])
        self.assertEqual(policy.entitlement, {})
        
        test_data = {
            'attachments': [{'id': '1', 'url': 'test.pdf'}],
            'applies_to': ['PERMANENT', 'CONTRACT'],
            'excludes': ['INTERN'],
            'entitlement': {'base_days': 20, 'additional_days': 5}
        }
        
        for field, value in test_data.items():
            setattr(policy, field, value)
        policy.save()
        
        policy.refresh_from_db()
        for field, value in test_data.items():
            self.assertEqual(getattr(policy, field), value)

    def test_employment_duration_custom(self):
        """Test employment duration custom days validation"""
        policy_data = self.default_policy_data.copy()
        policy_data.update({
            'employment_duration': 'CUSTOM',
            'employment_duration_custom_days': 90
        })
        
        policy = Policy.objects.create(**policy_data)
        self.assertEqual(policy.employment_duration_custom_days, 90)


class PolicyAuditModelTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.policy = Policy.objects.create(
            tenant_id=self.tenant_id,
            policy_name='Test Policy',
            policy_type='ANNUAL',
            created_by=self.user_id,
            updated_by=self.user_id
        )

    def test_audit_creation(self):
        """Test creating a new policy audit entry"""
        audit = PolicyAudit.objects.create(
            policy=self.policy,
            old_value={'status': 'PENDING_APPROVAL'},
            new_value={'status': 'ACTIVE'},
            update_type='STATUS_CHANGE',
            initiator_id=self.user_id,
            initiator_role='HR_MANAGER',
            initiator_name='John Doe',
            reason='Policy activation',
            comment='Approved by HR'
        )

        self.assertIsNotNone(audit.id)
        self.assertEqual(audit.policy, self.policy)
        self.assertTrue(isinstance(audit.timestamp_utc, datetime))

    def test_audit_ordering(self):
        """Test that audit entries are ordered by timestamp descending"""
        for i in range(3):
            PolicyAudit.objects.create(
                policy=self.policy,
                update_type=f'UPDATE_{i}',
                initiator_id=self.user_id
            )

        audits = PolicyAudit.objects.filter(policy=self.policy)
        timestamps = [audit.timestamp_utc for audit in audits]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_audit_string_representation(self):
        """Test the string representation of the PolicyAudit model"""
        audit = PolicyAudit.objects.create(
            policy=self.policy,
            update_type='STATUS_CHANGE',
            initiator_id=self.user_id
        )
        expected_str = f"STATUS_CHANGE - Test Policy @ {audit.timestamp_utc}"
        self.assertEqual(str(audit), expected_str)

    def test_audit_json_fields(self):
        """Test JSON fields in PolicyAudit"""
        test_data = {
            'old_value': {
                'status': 'PENDING_APPROVAL',
                'is_active': False
            },
            'new_value': {
                'status': 'ACTIVE',
                'is_active': True
            }
        }
        
        audit = PolicyAudit.objects.create(
            policy=self.policy,
            update_type='STATUS_CHANGE',
            initiator_id=self.user_id,
            **test_data
        )
        
        audit.refresh_from_db()
        self.assertEqual(audit.old_value, test_data['old_value'])
        self.assertEqual(audit.new_value, test_data['new_value'])