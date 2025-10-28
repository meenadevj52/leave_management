import uuid
from django.db import models
from django.utils import timezone

POLICY_STATUS_CHOICES = [
    ('PENDING_APPROVAL', 'Pending Approval'),
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUPERSEDED', 'Superseded'),
    ('REJECTED', 'Rejected'),
]

RESET_COUNTER_CHOICES = [
    ('BEGINNING_OF_YEAR', 'Beginning of Year'),
    ('EMPLOYMENT_ANNIVERSARY', 'Employment Anniversary'),
    ('CONTINUOUS', 'Continuous (No Reset)'),
]

EMPLOYMENT_DURATION_CHOICES = [
    ('IMMEDIATE', 'Immediate'),
    ('6_MONTHS', '6 Months'),
    ('1_YEAR', '1 Year'),
    ('2_YEARS', '2 Years'),
    ('CUSTOM', 'Custom'),
]

CALCULATION_BASE_CHOICES = [
    ('PER_DAY_SALARY', 'Per Day Wise Salary'),
    ('PER_HOUR_SALARY', 'Per Hour Salary'),
    ('MONTHLY_BASIC_SALARY', 'Monthly Basic Salary'),
    ('MONTHLY_GROSS_SALARY', 'Monthly Gross Salary'),
]


def get_default_conditions():
    """Returns default policy conditions for leave validation."""
    return [
        # === SICK LEAVE CONDITIONS ===
        {
            "id": "cond_sick_doc_required",
            "description": "Require medical certificate for Sick leave >3 days",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Sick"},
                {"field": "leave_days", "operator": "gt", "value": 3}
            ],
            "action_if_true": {
                "type": "require_documentation",
                "params": {"doc_type": "Medical Certificate", "editable": True, "threshold": 3}
            }
        },
        {
            "id": "cond_sick_fitness_cert",
            "description": "Require fitness certificate for Sick leave >14 days",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Sick"},
                {"field": "leave_days", "operator": "gt", "value": 14}
            ],
            "action_if_true": {
                "type": "require_fitness_certificate",
                "params": {"threshold": 14, "editable": True}
            }
        },
        {
            "id": "cond_sick_tenure_restriction",
            "description": "Limit sick leave to 5 days if tenure < 6 months",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Sick"},
                {"field": "tenure_months", "operator": "lt", "value": 6}
            ],
            "action_if_true": {
                "type": "set_entitlement",
                "params": {"days": 5}
            }
        },
        {
            "id": "cond_sick_no_encashment",
            "description": "Block encashment for Sick leave",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Sick"},
                {"field": "request_type", "operator": "eq", "value": "encashment"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Sick leave is not encashable", "editable": False}
            }
        },

        # === ANNUAL LEAVE CONDITIONS ===
        {
            "id": "cond_annual_balance_check",
            "description": "Allow Annual leave if <= accrual_balance",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Annual"},
                {"field": "leave_days", "operator": "lte", "value": "{accrual_balance}"}
            ],
            "action_if_true": {"type": "allow_request", "params": {}}
        },
        {
            "id": "cond_annual_exceed_balance",
            "description": "Reject Annual leave if > accrual_balance",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Annual"},
                {"field": "leave_days", "operator": "gt", "value": "{accrual_balance}"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Exceeds available balance", "editable": False}
            }
        },
        {
            "id": "cond_annual_tenure_entitlement",
            "description": "Set 20 days Annual leave if tenure >= 1 year",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Annual"},
                {"field": "tenure_years", "operator": "gte", "value": 1}
            ],
            "action_if_true": {"type": "set_entitlement", "params": {"days": 20}}
        },
        {
            "id": "cond_annual_manager_bonus",
            "description": "Add 5 extra Annual leave days for Managers",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Annual"},
                {"field": "role", "operator": "eq", "value": "Manager"}
            ],
            "action_if_true": {"type": "add_entitlement", "params": {"days": 5}}
        },
        {
            "id": "cond_annual_blackout",
            "description": "No Annual leave during blackout periods",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Annual"},
                {"field": "blackout_period_check", "operator": "eq", "value": True}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Leave during blackout period", "editable": True}
            }
        },

        # === CASUAL LEAVE CONDITIONS ===
        {
            "id": "cond_casual_tenure_restriction",
            "description": "Limit Casual leave to 5 days if tenure < 1 year",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Casual"},
                {"field": "tenure_years", "operator": "lt", "value": 1}
            ],
            "action_if_true": {"type": "set_entitlement", "params": {"days": 5}}
        },
        {
            "id": "cond_casual_intern_block",
            "description": "Block Casual leave for Interns",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Casual"},
                {"field": "role", "operator": "eq", "value": "Intern"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Casual leave not allowed for Interns", "editable": True}
            }
        },
        {
            "id": "cond_casual_monthly_limit",
            "description": "Limit Casual leave to monthly threshold",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Casual"},
                {"field": "prior_leave_count", "operator": "gt", "value": "{monthly_limit}"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Exceeds monthly limit", "editable": True}
            }
        },
        {
            "id": "cond_casual_no_encashment",
            "description": "Block encashment for Casual leave",
            "checks": [
                {"field": "leave_type", "operator": "eq", "value": "Casual"},
                {"field": "request_type", "operator": "eq", "value": "encashment"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Casual leave is not encashable", "editable": False}
            }
        },

        # === PROBATION RESTRICTIONS ===
        {
            "id": "cond_probation_restrict_annual_casual",
            "description": "Restrict Annual & Casual leave during probation",
            "checks": [
                {"field": "employment_type", "operator": "eq", "value": "Probation"},
                {"field": "leave_type", "operator": "in", "value": ["Annual", "Casual"]}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Leave type not allowed during probation", "editable": True}
            }
        },

        # === NOTICE PERIOD RESTRICTIONS ===
        {
            "id": "cond_notice_period_restrict",
            "description": "Only allow Sick/Emergency leave during notice period",
            "checks": [
                {"field": "notice_period_status", "operator": "eq", "value": True},
                {"field": "leave_type", "operator": "not_in", "value": ["Sick", "Emergency"]}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Only Sick/Emergency leave allowed during notice period", "editable": True}
            }
        },

        # === HOLIDAY OVERLAP ===
        {
            "id": "cond_holiday_overlap",
            "description": "Exclude holidays from leave day count",
            "checks": [
                {"field": "overlap_with_holiday", "operator": "eq", "value": True}
            ],
            "action_if_true": {
                "type": "adjust_leave_days",
                "params": {"exclude_holidays": True, "editable": False}
            }
        },

        # === ADVANCE NOTICE ===
        {
            "id": "cond_advance_notice",
            "description": "Require X days advance notice",
            "checks": [
                {"field": "leave_request_notice_days", "operator": "lt", "value": "{notice_period}"}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Insufficient advance notice", "editable": True}
            }
        },

        # === DOCUMENTATION CHECK ===
        {
            "id": "cond_doc_not_provided",
            "description": "Reject if required documentation not provided",
            "checks": [
                {"field": "documentation_required", "operator": "eq", "value": True},
                {"field": "documentation_provided", "operator": "eq", "value": False}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Required documentation not provided", "editable": False}
            }
        },

        # === ENCASHMENT CONDITIONS ===
        {
            "id": "cond_encashment_tenure",
            "description": "Allow encashment only if tenure >= 2 years",
            "checks": [
                {"field": "request_type", "operator": "eq", "value": "encashment"},
                {"field": "tenure_years", "operator": "lt", "value": 2}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Encashment requires minimum 2 years tenure", "editable": True}
            }
        },
        {
            "id": "cond_encashment_max_days",
            "description": "Require CFO approval if encashment > 10 days",
            "checks": [
                {"field": "request_type", "operator": "eq", "value": "encashment"},
                {"field": "encash_days", "operator": "gt", "value": 10}
            ],
            "action_if_true": {
                "type": "require_additional_approval",
                "params": {"approver_role": "CFO", "editable": True}
            }
        },
        {
            "id": "cond_encashment_balance",
            "description": "Block encashment if balance < 5 days",
            "checks": [
                {"field": "request_type", "operator": "eq", "value": "encashment"},
                {"field": "balance_leave", "operator": "lt", "value": 5}
            ],
            "action_if_true": {
                "type": "reject_request",
                "params": {"reason": "Insufficient balance for encashment", "editable": True}
            }
        },

        # === CARRY FORWARD CONDITIONS ===
        {
            "id": "cond_carry_forward_limit",
            "description": "Limit carry forward to max configured days",
            "checks": [
                {"field": "carry_forward_requested", "operator": "gt", "value": "{carry_forward_max}"}
            ],
            "action_if_true": {
                "type": "adjust_carry_forward",
                "params": {"max_days": "{carry_forward_max}"}
            }
        },
        {
            "id": "cond_carry_forward_expiry",
            "description": "Check if unused leave expires in X months",
            "checks": [
                {"field": "carry_forward_expiry_check", "operator": "eq", "value": True}
            ],
            "action_if_true": {
                "type": "expire_balance",
                "params": {"months": 12, "editable": True}
            }
        },
    ]


class Policy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    policy_name = models.CharField(max_length=255)
    policy_type = models.CharField(max_length=50, db_index=True)

    # Versioning
    major_version = models.IntegerField(default=1)
    minor_version = models.IntegerField(default=0)
    version = models.CharField(max_length=10, editable=False)

    description = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=100, blank=True, null=True)
    attachments = models.JSONField(default=list, blank=True)
    applies_to = models.JSONField(default=list, blank=True)
    excludes = models.JSONField(default=list, blank=True)

    # Core Parameters
    entitlement = models.JSONField(default=dict, blank=True)
    carry_forward = models.IntegerField(default=0)
    carry_forward_priority = models.BooleanField(
        default=True,
        help_text="If system prioritizes carry-forward before encashment"
    )
    encashment = models.IntegerField(default=0)
    encashment_priority = models.BooleanField(
        default=False,
        help_text="If system should prioritize encashment first"
    )
    calculation_base = models.CharField(
        max_length=50,
        choices=CALCULATION_BASE_CHOICES,
        default='PER_DAY_SALARY',
        help_text="Defines how salary is used for encashment calculation"
    )
    multiplier = models.FloatField(
        default=1.0,
        help_text="Multiplier for encashment calculation (e.g., 1.5x salary)"
    )
    notice_period = models.IntegerField(default=0)
    limit_per_month = models.IntegerField(default=0)

    # Reset Leave Counter
    reset_leave_counter = models.CharField(
        max_length=50,
        choices=RESET_COUNTER_CHOICES,
        default='BEGINNING_OF_YEAR',
        help_text="When leave balances reset each year"
    )

    # Employment Duration
    employment_duration = models.CharField(
        max_length=50,
        choices=EMPLOYMENT_DURATION_CHOICES,
        default='IMMEDIATE',
        help_text="Minimum service period to qualify for this policy"
    )
    employment_duration_custom_days = models.IntegerField(
        default=0,
        help_text="Custom duration in days if employment_duration is CUSTOM"
    )

    # Flags
    can_apply_previous_date = models.BooleanField(default=False)
    document_required = models.BooleanField(default=False)
    allow_multiple_day = models.BooleanField(default=True)
    allow_half_day = models.BooleanField(default=True)
    allow_comment = models.BooleanField(
        default=True,
        help_text="Whether users can add comments in leave request"
    )
    request_on_notice_period = models.BooleanField(default=True)

    # Change Description
    change_description = models.TextField(
        blank=True,
        null=True,
        help_text="Description of changes made in this version"
    )

    # Structured Rules for Leave Service
    approval_route = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of roles required for approval, e.g., ['HR_MANAGER', 'CHRO']"
    )
    
    conditions = models.JSONField(
        default=get_default_conditions,
        blank=True,
        help_text="List of structured validation rules for leave requests"
    )

    # Approval Workflow Tracking
    current_approval_step = models.IntegerField(default=0)

    # Status & control
    status = models.CharField(
        max_length=20,
        choices=POLICY_STATUS_CHOICES,
        default='PENDING_APPROVAL'
    )
    is_active = models.BooleanField(default=False)
    created_by = models.UUIDField()
    updated_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('tenant_id', 'policy_type', 'major_version', 'minor_version')
        indexes = [
            models.Index(fields=['tenant_id', 'policy_type', 'is_active']),
            models.Index(fields=['status']),
        ]

    def save(self, *args, **kwargs):
        self.version = f"v{self.major_version}.{self.minor_version}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.policy_name} ({self.policy_type}) - {self.version}"


class PolicyAudit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(Policy, related_name="audits", on_delete=models.CASCADE)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    update_type = models.CharField(max_length=50)
    timestamp_utc = models.DateTimeField(default=timezone.now)
    initiator_id = models.UUIDField()
    initiator_role = models.CharField(max_length=50, blank=True)
    initiator_name = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp_utc']
        indexes = [
            models.Index(fields=['policy', '-timestamp_utc']),
        ]

    def __str__(self):
        return f"{self.update_type} - {self.policy.policy_name} @ {self.timestamp_utc}"