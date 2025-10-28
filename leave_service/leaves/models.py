import uuid
from django.db import models
from django.utils import timezone

LEAVE_TYPE_CHOICES = [
    ('Annual', 'Annual Leave'),
    ('Sick', 'Sick Leave'),
    ('Casual', 'Casual Leave'),
    ('Maternity', 'Maternity Leave'),
    ('Paternity', 'Paternity Leave'),
    ('Emergency', 'Emergency Leave'),
    ('Unpaid', 'Unpaid Leave'),
]

APPLICATION_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('APPROVED', 'Approved'),
    ('REJECTED', 'Rejected'),
    ('CANCELLED', 'Cancelled'),
    ('WITHDRAWN', 'Withdrawn'),
]

APPROVAL_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('APPROVED', 'Approved'),
    ('REJECTED', 'Rejected'),
    ('SKIPPED', 'Skipped'),
]

REQUEST_TYPE_CHOICES = [
    ('leave', 'Leave Request'),
    ('encashment', 'Encashment Request'),
]


class LeaveBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    employee_id = models.UUIDField(db_index=True)
    leave_type = models.CharField(max_length=50, choices=LEAVE_TYPE_CHOICES)
    
    total_allocated = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    used = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pending = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    available = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    carried_forward = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    carry_forward_expiry_date = models.DateField(null=True, blank=True)
    
    encashed = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    year = models.IntegerField()
    reset_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('tenant_id', 'employee_id', 'leave_type', 'year')
        indexes = [
            models.Index(fields=['tenant_id', 'employee_id']),
            models.Index(fields=['year']),
        ]
        ordering = ['-year', 'leave_type']

    def __str__(self):
        return f"{self.employee_id} - {self.leave_type} ({self.year}): {self.available}/{self.total_allocated}"

    def update_balance(self):
        """Recalculate available balance."""
        self.available = self.total_allocated - self.used - self.pending
        self.save()


class LeaveApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    employee_id = models.UUIDField(db_index=True)
    
    leave_type = models.CharField(max_length=50, choices=LEAVE_TYPE_CHOICES)
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, default='leave')
    
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.DecimalField(max_digits=5, decimal_places=2)
    is_half_day = models.BooleanField(default=False)
    half_day_period = models.CharField(max_length=20, blank=True, null=True)
    
    reason = models.TextField()
    comments = models.TextField(blank=True, null=True)
    
    documentation_required = models.BooleanField(default=False)
    required_doc_type = models.CharField(max_length=100, blank=True, null=True)
    attachments = models.JSONField(default=list, blank=True)
    
    encashment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    encashment_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    policy_id = models.UUIDField(null=True, blank=True)
    policy_version = models.CharField(max_length=20, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=APPLICATION_STATUS_CHOICES, default='PENDING')
    current_approval_step = models.IntegerField(default=0)
    
    approval_chain = models.JSONField(default=list, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    is_cancelled = models.BooleanField(default=False)
    cancelled_by = models.UUIDField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    
    created_by = models.UUIDField()
    updated_by = models.UUIDField()

    class Meta:
        ordering = ['-applied_at']
        indexes = [
            models.Index(fields=['tenant_id', 'employee_id']),
            models.Index(fields=['status']),
            models.Index(fields=['leave_type']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.employee_id} - {self.leave_type} ({self.start_date} to {self.end_date})"

    def can_be_cancelled(self):
        if self.status in ['CANCELLED', 'REJECTED']:
            return False
        if self.start_date < timezone.now().date():
            return False
        return True


class LeaveApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leave_application = models.ForeignKey(LeaveApplication, related_name='approvals', on_delete=models.CASCADE)
    
    step_number = models.IntegerField()
    approver_role = models.CharField(max_length=50)
    approver_id = models.UUIDField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='PENDING')
    
    comments = models.TextField(blank=True, null=True)
    actioned_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('leave_application', 'step_number')
        ordering = ['step_number']

    def __str__(self):
        return f"Step {self.step_number} - {self.approver_role} - {self.status}"


class LeaveComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leave_application = models.ForeignKey(LeaveApplication, related_name='leave_comments', on_delete=models.CASCADE)
    
    comment = models.TextField()
    commented_by = models.UUIDField()
    commented_by_name = models.CharField(max_length=255, blank=True, null=True)
    commented_by_role = models.CharField(max_length=50, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.commented_by_name} on {self.leave_application.id}"


class LeaveCommentReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey(LeaveComment, related_name='replies', on_delete=models.CASCADE)
    
    reply = models.TextField()
    replied_by = models.UUIDField()
    replied_by_name = models.CharField(max_length=255, blank=True, null=True)
    replied_by_role = models.CharField(max_length=50, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Reply by {self.replied_by_name}"


class LeaveAudit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leave_application = models.ForeignKey(LeaveApplication, related_name='audit_logs', on_delete=models.CASCADE)
    
    action = models.CharField(max_length=50)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    
    performed_by = models.UUIDField()
    performed_by_name = models.CharField(max_length=255, blank=True, null=True)
    performed_by_role = models.CharField(max_length=50, blank=True, null=True)
    
    reason = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['leave_application', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.action} by {self.performed_by_name} at {self.timestamp}"


class Holiday(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    
    name = models.CharField(max_length=255)
    date = models.DateField()
    is_optional = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tenant_id', 'date')
        ordering = ['date']

    def __str__(self):
        return f"{self.name} - {self.date}"