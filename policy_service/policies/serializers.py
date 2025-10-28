import uuid
from rest_framework import serializers
from .models import Policy, PolicyAudit


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None



class PolicySerializer(serializers.ModelSerializer):
    approval_route = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        required=False,
        help_text="Ordered list of roles for approval workflow, e.g., ['HR_MANAGER', 'CHRO']"
    )
    conditions = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True,
        required=False,
        help_text="List of structured validation rules"
    )
    change_description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Description of changes in this version"
    )

    class Meta:
        model = Policy
        fields = '__all__'
        read_only_fields = (
            'id', 'version', 'status', 'is_active', 'created_at',
            'updated_at', 'tenant_id', 'created_by', 'updated_by',
            'major_version', 'minor_version', 'current_approval_step'
        )

    def validate_approval_route(self, value):
        if not value:
            raise serializers.ValidationError("Approval route cannot be empty.")

        if not all(isinstance(role, str) for role in value):
            raise serializers.ValidationError("All items in approval_route must be strings.")

        return value

    def validate_conditions(self, value):
        for idx, condition in enumerate(value):
            if 'id' not in condition:
                raise serializers.ValidationError(f"Condition at index {idx} missing 'id'.")

            if 'checks' not in condition or not isinstance(condition['checks'], list):
                raise serializers.ValidationError(f"Condition '{condition.get('id')}' must have 'checks' as a list.")

            for check in condition['checks']:
                if not all(k in check for k in ['field', 'operator', 'value']):
                    raise serializers.ValidationError(
                        f"Check in condition '{condition.get('id')}' must have 'field', 'operator', and 'value'."
                    )

            if 'action_if_true' not in condition:
                raise serializers.ValidationError(f"Condition '{condition.get('id')}' missing 'action_if_true'.")

        return value

    def validate(self, data):
        employment_duration = data.get('employment_duration')
        custom_days = data.get('employment_duration_custom_days', 0)

        if employment_duration == 'CUSTOM' and custom_days <= 0:
            raise serializers.ValidationError({
                'employment_duration_custom_days': 'Must be greater than 0 when duration is CUSTOM'
            })

        carry_forward_priority = data.get('carry_forward_priority')
        encashment_priority = data.get('encashment_priority')

        if carry_forward_priority and encashment_priority:
            raise serializers.ValidationError({
                'carry_forward_priority': 'Cannot set both carry_forward_priority and encashment_priority to True',
                'encashment_priority': 'Cannot set both carry_forward_priority and encashment_priority to True'
            })

        multiplier = data.get('multiplier', 1.0)
        if multiplier <= 0:
            raise serializers.ValidationError({
                'multiplier': 'Multiplier must be greater than 0'
            })

        return data

    def create(self, validated_data):
        tenant_id = validated_data.get('tenant_id')
        policy_type = validated_data.get('policy_type')

        last_policy = Policy.objects.filter(
            tenant_id=tenant_id,
            policy_type=policy_type
        ).order_by('-created_at').first()

        if last_policy:
            validated_data['major_version'] = last_policy.major_version
            validated_data['minor_version'] = last_policy.minor_version + 1
        else:
            validated_data['major_version'] = 1
            validated_data['minor_version'] = 0

        validated_data['status'] = "PENDING_APPROVAL"
        validated_data['is_active'] = False
        validated_data['current_approval_step'] = 0

        return super().create(validated_data)

    def update(self, instance, validated_data):
        user = self.context['request'].user

        instance.status = "SUPERSEDED"
        instance.is_active = False
        instance.save()

        new_policy_data = {
            'tenant_id': instance.tenant_id,
            'policy_type': instance.policy_type,
            'policy_name': validated_data.get('policy_name', instance.policy_name),
            'description': validated_data.get('description', instance.description),
            'location': validated_data.get('location', instance.location),
            'attachments': validated_data.get('attachments', instance.attachments),
            'applies_to': validated_data.get('applies_to', instance.applies_to),
            'excludes': validated_data.get('excludes', instance.excludes),
            'entitlement': validated_data.get('entitlement', instance.entitlement),
            'carry_forward': validated_data.get('carry_forward', instance.carry_forward),
            'carry_forward_priority': validated_data.get('carry_forward_priority', instance.carry_forward_priority),
            'encashment': validated_data.get('encashment', instance.encashment),
            'encashment_priority': validated_data.get('encashment_priority', instance.encashment_priority),
            'calculation_base': validated_data.get('calculation_base', instance.calculation_base),
            'multiplier': validated_data.get('multiplier', instance.multiplier),
            'notice_period': validated_data.get('notice_period', instance.notice_period),
            'limit_per_month': validated_data.get('limit_per_month', instance.limit_per_month),
            'reset_leave_counter': validated_data.get('reset_leave_counter', instance.reset_leave_counter),
            'employment_duration': validated_data.get('employment_duration', instance.employment_duration),
            'employment_duration_custom_days': validated_data.get('employment_duration_custom_days', instance.employment_duration_custom_days),
            'can_apply_previous_date': validated_data.get('can_apply_previous_date', instance.can_apply_previous_date),
            'document_required': validated_data.get('document_required', instance.document_required),
            'allow_multiple_day': validated_data.get('allow_multiple_day', instance.allow_multiple_day),
            'allow_half_day': validated_data.get('allow_half_day', instance.allow_half_day),
            'allow_comment': validated_data.get('allow_comment', instance.allow_comment),
            'request_on_notice_period': validated_data.get('request_on_notice_period', instance.request_on_notice_period),
            'approval_route': validated_data.get('approval_route', instance.approval_route),
            'conditions': validated_data.get('conditions', instance.conditions),
            'change_description': validated_data.get('change_description', ''),

            'major_version': instance.major_version,
            'minor_version': instance.minor_version + 1,

            'status': "PENDING_APPROVAL",
            'is_active': False,
            'current_approval_step': 0,
            'created_by': instance.created_by,
            'updated_by': to_uuid(user.id),
        }

        new_policy = Policy.objects.create(**new_policy_data)

        from .views import clean_policy_data
        from django.utils import timezone
        from .models import PolicyAudit

        PolicyAudit.objects.create(
            policy=new_policy,
            old_value=clean_policy_data(instance),
            new_value=clean_policy_data(new_policy),
            update_type="VERSIONED_UPDATE",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(user.id),
            initiator_role=user.role,
            initiator_name=getattr(user, "username", ""),
            reason=validated_data.get('change_description', 'Policy updated')
        )

        return new_policy


class PolicyAuditSerializer(serializers.ModelSerializer):

    class Meta:
        model = PolicyAudit
        fields = '__all__'
        read_only_fields = ('id', 'timestamp_utc')