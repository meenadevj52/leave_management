import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.db.utils import IntegrityError
from ..models import (
    LeaveBalance,
    LeaveApplication,
    LeaveApproval,
    LeaveComment,
    LeaveCommentReply,
    LeaveAudit,
    Holiday
)

class LeaveBalanceTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.balance = LeaveBalance.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            total_allocated=Decimal('20.00'),
            used=Decimal('5.00'),
            pending=Decimal('2.00'),
            year=2025
        )
        self.balance.update_balance()

    def test_leave_balance_creation(self):
        """Test if LeaveBalance instance is created correctly"""
        self.assertEqual(self.balance.total_allocated, Decimal('20.00'))
        self.assertEqual(self.balance.used, Decimal('5.00'))
        self.assertEqual(self.balance.pending, Decimal('2.00'))
        self.assertEqual(self.balance.available, Decimal('13.00'))

    def test_update_balance(self):
        """Test if balance is updated correctly"""
        self.balance.used = Decimal('10.00')
        self.balance.update_balance()
        self.assertEqual(self.balance.available, Decimal('8.00'))

    def test_unique_constraint(self):
        """Test unique constraint for tenant, employee, leave_type and year"""
        with self.assertRaises(IntegrityError):
            LeaveBalance.objects.create(
                tenant_id=self.tenant_id,
                employee_id=self.employee_id,
                leave_type='Annual',
                year=2025
            )

class LeaveApplicationTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.created_by = uuid.uuid4()
        self.updated_by = uuid.uuid4()
        
        self.application = LeaveApplication.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            total_days=Decimal('3.00'),
            reason="Annual vacation",
            created_by=self.created_by,
            updated_by=self.updated_by
        )

    def test_leave_application_creation(self):
        """Test if LeaveApplication instance is created correctly"""
        self.assertEqual(self.application.status, 'PENDING')
        self.assertEqual(self.application.current_approval_step, 0)
        self.assertEqual(self.application.total_days, Decimal('3.00'))

    def test_can_be_cancelled_pending(self):
        """Test if leave can be cancelled when pending and future dated"""
        future_date = timezone.now().date() + timedelta(days=5)
        self.application.start_date = future_date
        self.application.end_date = future_date + timedelta(days=2)
        self.application.save()
        
        self.assertTrue(self.application.can_be_cancelled())

    def test_cannot_cancel_past_leave(self):
        """Test that past leaves cannot be cancelled"""
        past_date = timezone.now().date() - timedelta(days=5)
        self.application.start_date = past_date
        self.application.end_date = past_date + timedelta(days=2)
        self.application.save()
        
        self.assertFalse(self.application.can_be_cancelled())

    def test_cannot_cancel_rejected_leave(self):
        """Test that rejected leaves cannot be cancelled"""
        self.application.status = 'REJECTED'
        self.application.save()
        
        self.assertFalse(self.application.can_be_cancelled())

class LeaveApprovalTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.created_by = uuid.uuid4()
        self.updated_by = uuid.uuid4()
        
        self.application = LeaveApplication.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            total_days=Decimal('3.00'),
            reason="Annual vacation",
            created_by=self.created_by,
            updated_by=self.updated_by
        )
        
        self.approval = LeaveApproval.objects.create(
            leave_application=self.application,
            step_number=1,
            approver_role='MANAGER',
            approver_id=uuid.uuid4()
        )

    def test_leave_approval_creation(self):
        """Test if LeaveApproval instance is created correctly"""
        self.assertEqual(self.approval.status, 'PENDING')
        self.assertEqual(self.approval.step_number, 1)
        self.assertEqual(self.approval.approver_role, 'MANAGER')

    def test_unique_step_constraint(self):
        """Test unique constraint for leave_application and step_number"""
        with self.assertRaises(IntegrityError):
            LeaveApproval.objects.create(
                leave_application=self.application,
                step_number=1,
                approver_role='SUPERVISOR'
            )

class LeaveCommentTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.created_by = uuid.uuid4()
        self.updated_by = uuid.uuid4()
        
        self.application = LeaveApplication.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            total_days=Decimal('3.00'),
            reason="Annual vacation",
            created_by=self.created_by,
            updated_by=self.updated_by
        )
        
        self.comment = LeaveComment.objects.create(
            leave_application=self.application,
            comment="Please provide more details",
            commented_by=uuid.uuid4(),
            commented_by_name="John Manager",
            commented_by_role="MANAGER"
        )

    def test_comment_creation(self):
        """Test if LeaveComment instance is created correctly"""
        self.assertEqual(self.comment.comment, "Please provide more details")
        self.assertEqual(self.comment.commented_by_name, "John Manager")
        self.assertEqual(self.comment.commented_by_role, "MANAGER")

class LeaveCommentReplyTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.created_by = uuid.uuid4()
        self.updated_by = uuid.uuid4()
        
        self.application = LeaveApplication.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            total_days=Decimal('3.00'),
            reason="Annual vacation",
            created_by=self.created_by,
            updated_by=self.updated_by
        )
        
        self.comment = LeaveComment.objects.create(
            leave_application=self.application,
            comment="Please provide more details",
            commented_by=uuid.uuid4(),
            commented_by_name="John Manager",
            commented_by_role="MANAGER"
        )
        
        self.reply = LeaveCommentReply.objects.create(
            comment=self.comment,
            reply="Details provided in attachment",
            replied_by=self.employee_id,
            replied_by_name="Jane Employee",
            replied_by_role="EMPLOYEE"
        )

    def test_reply_creation(self):
        """Test if LeaveCommentReply instance is created correctly"""
        self.assertEqual(self.reply.reply, "Details provided in attachment")
        self.assertEqual(self.reply.replied_by_name, "Jane Employee")
        self.assertEqual(self.reply.replied_by_role, "EMPLOYEE")

class LeaveAuditTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee_id = uuid.uuid4()
        self.created_by = uuid.uuid4()
        self.updated_by = uuid.uuid4()
        
        self.application = LeaveApplication.objects.create(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            leave_type='Annual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            total_days=Decimal('3.00'),
            reason="Annual vacation",
            created_by=self.created_by,
            updated_by=self.updated_by
        )
        
        self.audit = LeaveAudit.objects.create(
            leave_application=self.application,
            action="STATUS_CHANGE",
            old_value={"status": "PENDING"},
            new_value={"status": "APPROVED"},
            performed_by=uuid.uuid4(),
            performed_by_name="John Manager",
            performed_by_role="MANAGER"
        )

    def test_audit_creation(self):
        """Test if LeaveAudit instance is created correctly"""
        self.assertEqual(self.audit.action, "STATUS_CHANGE")
        self.assertEqual(self.audit.old_value["status"], "PENDING")
        self.assertEqual(self.audit.new_value["status"], "APPROVED")
        self.assertEqual(self.audit.performed_by_role, "MANAGER")

class HolidayTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.holiday = Holiday.objects.create(
            tenant_id=self.tenant_id,
            name="New Year's Day",
            date=date(2025, 1, 1)
        )

    def test_holiday_creation(self):
        """Test if Holiday instance is created correctly"""
        self.assertEqual(self.holiday.name, "New Year's Day")
        self.assertEqual(self.holiday.date, date(2025, 1, 1))
        self.assertFalse(self.holiday.is_optional)

    def test_unique_constraint(self):
        """Test unique constraint for tenant and date"""
        with self.assertRaises(IntegrityError):
            Holiday.objects.create(
                tenant_id=self.tenant_id,
                name="Duplicate Holiday",
                date=date(2025, 1, 1)
            )