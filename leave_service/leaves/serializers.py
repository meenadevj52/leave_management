import uuid
from rest_framework import serializers
from decimal import Decimal
from datetime import datetime, date
from .models import (
    LeaveApplication, LeaveApproval, LeaveBalance, 
    LeaveComment, LeaveCommentReply, LeaveAudit, Holiday
)
from .services.validation_service import LeaveValidationService


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


class LeaveBalanceSerializer(serializers.ModelSerializer):

    class Meta:
        model = LeaveBalance
        fields = '__all__'
        read_only_fields = ('id', 'tenant_id', 'employee_id', 'created_at', 'updated_at')


class LeaveApprovalSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(read_only=True, source='approver_id')
    
    class Meta:
        model = LeaveApproval
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class LeaveCommentReplySerializer(serializers.ModelSerializer):
    
    class Meta:
        model = LeaveCommentReply
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class LeaveCommentSerializer(serializers.ModelSerializer):

    replies = LeaveCommentReplySerializer(many=True, read_only=True)
    
    class Meta:
        model = LeaveComment
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class LeaveAuditSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = LeaveAudit
        fields = '__all__'
        read_only_fields = ('id', 'timestamp')


class LeaveApplicationListSerializer(serializers.ModelSerializer):
    approvals_summary = serializers.SerializerMethodField()
    employee_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = LeaveApplication
        fields = [
            'id', 'employee_id', 'employee_name', 'leave_type', 'request_type',
            'start_date', 'end_date', 'total_days', 'status', 'reason',
            'applied_at', 'approvals_summary', 'is_cancelled'
        ]
    
    def get_approvals_summary(self, obj):

        approvals = obj.approvals.all()
        return {
            'total_steps': len(approvals),
            'current_step': obj.current_approval_step,
            'pending_with': approvals.filter(status='PENDING').first().approver_role if approvals.filter(status='PENDING').exists() else None
        }


class LeaveApplicationDetailSerializer(serializers.ModelSerializer):
    approvals = LeaveApprovalSerializer(many=True, read_only=True)
    leave_comments = LeaveCommentSerializer(many=True, read_only=True)
    employee_details = serializers.SerializerMethodField()
    
    class Meta:
        model = LeaveApplication
        fields = '__all__'
        read_only_fields = (
            'id', 'tenant_id', 'employee_id', 'status', 'current_approval_step',
            'approval_chain', 'applied_at', 'updated_at', 'approved_at', 
            'rejected_at', 'created_by', 'updated_by', 'total_days',
            'documentation_required', 'required_doc_type'
        )
    
    def get_employee_details(self, obj):
        return self.context.get('employee_details', {})


class LeaveApplicationCreateSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = LeaveApplication
        fields = [
            'leave_type', 'request_type', 'start_date', 'end_date', 
            'is_half_day', 'half_day_period', 'reason', 'comments',
            'attachments', 'encashment_days'
        ]
    
    def validate(self, data):
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        leave_type = data.get('leave_type')
        request_type = data.get('request_type', 'leave')
        is_half_day = data.get('is_half_day', False)
        
        if start_date > end_date:
            raise serializers.ValidationError({
                'end_date': 'End date must be after start date.'
            })
        
        if start_date < date.today():
            pass
        
        if is_half_day and start_date != end_date:
            raise serializers.ValidationError({
                'is_half_day': 'Half-day leave can only be for a single day.'
            })
        
        if is_half_day and not data.get('half_day_period'):
            raise serializers.ValidationError({
                'half_day_period': 'Half-day period (morning/afternoon) is required for half-day leave.'
            })
        
        if request_type == 'encashment':
            if leave_type not in ['Annual']:
                raise serializers.ValidationError({
                    'leave_type': 'Encashment is only allowed for Annual leave.'
                })
            
            if not data.get('encashment_days') or data.get('encashment_days') <= 0:
                raise serializers.ValidationError({
                    'encashment_days': 'Encashment days must be greater than 0.'
                })
        
        return data
    
    def create(self, validated_data):
        return super().create(validated_data)


class LeaveApplicationApprovalSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    comments = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        if data['action'] == 'reject' and not data.get('comments'):
            raise serializers.ValidationError({
                'comments': 'Comments are required when rejecting a leave application.'
            })
        return data


class LeaveApplicationCancelSerializer(serializers.Serializer):
    cancellation_reason = serializers.CharField(required=True)


class HolidaySerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Holiday
        fields = '__all__'
        read_only_fields = ('id', 'tenant_id', 'created_at')


class LeaveBalanceSummarySerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    employee_name = serializers.CharField()
    year = serializers.IntegerField()
    balances = serializers.ListField(child=serializers.DictField())

class LeaveStatisticsSerializer(serializers.Serializer):
    total_applications = serializers.IntegerField()
    pending_applications = serializers.IntegerField()
    approved_applications = serializers.IntegerField()
    rejected_applications = serializers.IntegerField()
    total_days_taken = serializers.DecimalField(max_digits=5, decimal_places=2)
    leave_by_type = serializers.DictField()