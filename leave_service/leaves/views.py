import uuid
from datetime import datetime, date
from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum, F
from django.utils import timezone

from .models import (
    LeaveApplication, LeaveApproval, LeaveBalance,
    LeaveComment, LeaveCommentReply, LeaveAudit, Holiday
)
from .serializers import (
    LeaveApplicationListSerializer, LeaveApplicationDetailSerializer,
    LeaveApplicationCreateSerializer, LeaveApplicationApprovalSerializer,
    LeaveApplicationCancelSerializer, LeaveBalanceSerializer,
    LeaveCommentSerializer, LeaveCommentReplySerializer,
    LeaveAuditSerializer, HolidaySerializer, LeaveBalanceSummarySerializer,
    LeaveStatisticsSerializer, LeaveApprovalSerializer
)
from .permissions import IsEmployee, IsHROrAdmin, IsOwnerOrApprover, IsApprover
from .authentication import AuthServiceTokenAuthentication
from .services.policy_service import PolicyServiceClient
from .services.employee_service import EmployeeServiceClient
from .services.validation_service import LeaveValidationService
from .tasks import send_leave_event
from .utils import to_uuid, clean_leave_data


class LeaveApplicationViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return LeaveApplicationCreateSerializer
        elif self.action in ['list', 'my_leaves']:
            return LeaveApplicationListSerializer
        else:
            return LeaveApplicationDetailSerializer
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        queryset = LeaveApplication.objects.filter(tenant_id=tenant_id)
        
        if user.role in ['HR', 'ADMIN', 'HR_MANAGER']:
            return queryset
        else:
            return queryset.filter(
                Q(employee_id=to_uuid(user.id)) |
                Q(approvals__approver_id=to_uuid(user.id))
            ).distinct()
    
    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        employee_id = to_uuid(user.id)
        
        employee = EmployeeServiceClient.get_employee_details(employee_id)
        if not employee:
            raise ValidationError({'error': 'Employee details not found'})
        
        leave_type = serializer.validated_data['leave_type']
        policy = PolicyServiceClient.get_active_policy(tenant_id, leave_type)
        
        if not policy:
            raise ValidationError({
                'error': f'No active policy found for {leave_type} leave type.'
            })
        
        start_date = serializer.validated_data['start_date']
        end_date = serializer.validated_data['end_date']
        is_half_day = serializer.validated_data.get('is_half_day', False)
        
        total_days, holidays_count = LeaveValidationService.calculate_leave_days(
            start_date, end_date, is_half_day, tenant_id
        )
        
        if LeaveValidationService.check_leave_overlap(employee_id, start_date, end_date):
            raise ValidationError({
                'error': 'You have overlapping leave applications for these dates.'
            })
        
        current_year = date.today().year
        balance = LeaveValidationService.get_or_create_balance(
            tenant_id, employee_id, leave_type, current_year,
            total_allocated=policy.get('entitlement', {}).get('base_days', 0)
        )
        
        leave_request_data = {
            'leave_type': leave_type,
            'leave_days': float(total_days),
            'start_date': str(start_date),
            'end_date': str(end_date),
            'request_type': serializer.validated_data.get('request_type', 'leave'),
            'employment_type': employee.get('employment_type'),
            'documentation_provided': len(serializer.validated_data.get('attachments', [])) > 0
        }
        
        employee_data = {
            'role': employee.get('designation', employee.get('role')),
            'department': employee.get('department'),
            'manager_id': str(employee.get('manager_id')) if employee.get('manager_id') else None,
            'tenure_months': self._calculate_tenure_months(employee.get('joining_date')),
            'tenure_years': self._calculate_tenure_years(employee.get('joining_date')),
            'employment_type': employee.get('employment_type')
        }
        
        context = {
            'accrual_balance': float(balance.available),
            'monthly_limit': policy.get('limit_per_month', 0),
            'prior_leave_count': self._get_monthly_leave_count(employee_id, leave_type),
            'notice_period': policy.get('notice_period', 0),
            'leave_request_notice_days': (start_date - date.today()).days,
            'notice_period_status': employee.get('is_in_notice_period', False),
            'overlap_with_holiday': holidays_count > 0,
            'holidays_in_range': holidays_count,
            'blackout_period_check': False,
            'carry_forward_max': policy.get('carry_forward', 0)
        }

        validation_result = self._validate_against_policy(
            policy, leave_request_data, employee_data, context
        )
        
        if not validation_result['is_valid']:
            errors = [error['reason'] for error in validation_result['errors']]
            raise ValidationError({
                'error': 'Leave request validation failed',
                'reasons': errors,
                'details': validation_result['errors']
            })
        
        if serializer.validated_data.get('request_type', 'leave') == 'leave':
            if not LeaveValidationService.check_sufficient_balance(
                employee_id, leave_type, total_days, current_year
            ):
                raise ValidationError({
                    'error': 'Insufficient leave balance',
                    'available': float(balance.available),
                    'requested': float(total_days)
                })
        
        encashment_amount = Decimal('0')
        if serializer.validated_data.get('request_type') == 'encashment':
            encashment_days = Decimal(str(serializer.validated_data.get('encashment_days', 0)))
            salary_per_day = Decimal(str(employee.get('salary_per_day', 0)))
            
            encashment_result = LeaveValidationService.calculate_encashment(
                policy, balance.available, encashment_days, salary_per_day
            )
            
            if not encashment_result['allowed']:
                raise ValidationError({'error': encashment_result['reason']})
            
            encashment_amount = Decimal(str(encashment_result['amount']))
        
        leave_app = serializer.save(
            tenant_id=tenant_id,
            employee_id=employee_id,
            total_days=total_days,
            policy_id=to_uuid(policy['id']),
            policy_version=policy['version'],
            approval_chain=validation_result['approval_chain'],
            status='PENDING',
            current_approval_step=0,
            created_by=employee_id,
            updated_by=employee_id,
            encashment_amount=encashment_amount
        )
        
        for approval_step in validation_result['approval_chain']:
            LeaveApproval.objects.create(
                leave_application=leave_app,
                step_number=approval_step['step'],
                approver_role=approval_step['role'],
                approver_id=to_uuid(approval_step.get('user_id')) if approval_step.get('user_id') else None,
                status='PENDING'
            )
        
        if serializer.validated_data.get('request_type', 'leave') == 'leave':
            balance.pending += total_days
            balance.update_balance()
        
        LeaveAudit.objects.create(
            leave_application=leave_app,
            action='CREATE',
            new_value=clean_leave_data(leave_app),
            performed_by=employee_id,
            performed_by_name=employee.get('full_name', user.email),
            performed_by_role=user.role,
            reason='Leave application submitted'
        )
        
        send_leave_event('leave_application_created', {
            'leave_application_id': str(leave_app.id),
            'employee_id': str(employee_id),
            'leave_type': leave_type,
            'start_date': str(start_date),
            'end_date': str(end_date),
            'total_days': float(total_days),
            'status': 'PENDING',
            'tenant_id': str(tenant_id)
        })
    
    def _validate_against_policy(self, policy, leave_data, employee_data, context):
        errors = []
        
        if leave_data['leave_days'] > context['accrual_balance']:
            errors.append({
                'condition_id': 'balance_check',
                'reason': 'Insufficient leave balance'
            })
        
        if employee_data.get('employment_type') == 'Probation' and leave_data['leave_type'] in ['Annual', 'Casual']:
            errors.append({
                'condition_id': 'probation_check',
                'reason': 'Leave type not allowed during probation'
            })
        
        approval_chain = []
        for idx, role in enumerate(policy.get('approval_route', [])):
            approval_chain.append({
                'step': idx,
                'role': role,
                'user_id': employee_data.get('manager_id') if role == 'REPORTING_MANAGER' else None
            })
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'actions': [],
            'approval_chain': approval_chain
        }
    
    @action(detail=True, methods=['post'], url_path='approve')
    @transaction.atomic
    def approve_leave(self, request, pk=None):
        leave_app = self.get_object()
        user = request.user
        
        try:
            current_approval = leave_app.approvals.get(
                step_number=leave_app.current_approval_step,
                approver_id=to_uuid(user.id)
            )
        except LeaveApproval.DoesNotExist:
            raise PermissionDenied("You are not authorized to approve this leave application at this step.")
        
        if current_approval.status != 'PENDING':
            raise ValidationError(f"This approval step is already {current_approval.status}.")
        
        serializer = LeaveApplicationApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        comments = serializer.validated_data.get('comments', '')
        
        if action == 'approve':
            current_approval.status = 'APPROVED'
            current_approval.comments = comments
            current_approval.actioned_at = timezone.now()
            current_approval.save()
            
            leave_app.current_approval_step += 1
            
            if leave_app.current_approval_step >= leave_app.approvals.count():
                leave_app.status = 'APPROVED'
                leave_app.approved_at = timezone.now()
                
                if leave_app.request_type == 'leave':
                    balance = LeaveBalance.objects.get(
                        employee_id=leave_app.employee_id,
                        leave_type=leave_app.leave_type,
                        year=date.today().year
                    )
                    balance.pending -= leave_app.total_days
                    balance.used += leave_app.total_days
                    balance.update_balance()
                
                event_name = 'leave_application_approved'
            else:
                event_name = 'leave_application_step_approved'
            
            leave_app.save()
            
            LeaveAudit.objects.create(
                leave_application=leave_app,
                action='APPROVE_STEP',
                new_value={'step': current_approval.step_number, 'status': 'APPROVED'},
                performed_by=to_uuid(user.id),
                performed_by_name=user.email,
                performed_by_role=user.role,
                reason=comments
            )
            
            send_leave_event(event_name, {
                'leave_application_id': str(leave_app.id),
                'employee_id': str(leave_app.employee_id),
                'status': leave_app.status,
                'approved_by': str(user.id),
                'step_number': current_approval.step_number,
                'tenant_id': str(leave_app.tenant_id)
            })
            
            return Response({
                'message': 'Leave application approved successfully',
                'status': leave_app.status,
                'current_step': leave_app.current_approval_step,
                'total_steps': leave_app.approvals.count()
            }, status=status.HTTP_200_OK)
        
        else:
            current_approval.status = 'REJECTED'
            current_approval.comments = comments
            current_approval.actioned_at = timezone.now()
            current_approval.save()
            
            leave_app.status = 'REJECTED'
            leave_app.rejection_reason = comments
            leave_app.rejected_at = timezone.now()
            leave_app.save()
            
            if leave_app.request_type == 'leave':
                balance = LeaveBalance.objects.get(
                    employee_id=leave_app.employee_id,
                    leave_type=leave_app.leave_type,
                    year=date.today().year
                )
                balance.pending -= leave_app.total_days
                balance.update_balance()
            
            LeaveAudit.objects.create(
                leave_application=leave_app,
                action='REJECT',
                new_value={'status': 'REJECTED'},
                performed_by=to_uuid(user.id),
                performed_by_name=user.email,
                performed_by_role=user.role,
                reason=comments
            )
            
            send_leave_event('leave_application_rejected', {
                'leave_application_id': str(leave_app.id),
                'employee_id': str(leave_app.employee_id),
                'rejected_by': str(user.id),
                'reason': comments,
                'tenant_id': str(leave_app.tenant_id)
            })
            
            return Response({
                'message': 'Leave application rejected',
                'status': 'REJECTED',
                'reason': comments
            }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], url_path='cancel')
    @transaction.atomic
    def cancel_leave(self, request, pk=None):
        leave_app = self.get_object()
        user = request.user
        
        if str(leave_app.employee_id) != str(user.id):
            raise PermissionDenied("You can only cancel your own leave applications.")

        if not leave_app.can_be_cancelled():
            raise ValidationError({
                'error': 'Leave cannot be cancelled',
                'reason': 'Leave has already started or is already cancelled/rejected'
            })
        
        serializer = LeaveApplicationCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        leave_app.is_cancelled = True
        leave_app.status = 'CANCELLED'
        leave_app.cancelled_by = to_uuid(user.id)
        leave_app.cancelled_at = timezone.now()
        leave_app.cancellation_reason = serializer.validated_data['cancellation_reason']
        leave_app.save()

        if leave_app.request_type == 'leave':
            balance = LeaveBalance.objects.get(
                employee_id=leave_app.employee_id,
                leave_type=leave_app.leave_type,
                year=date.today().year
            )
            
            if leave_app.status == 'APPROVED':
                balance.used -= leave_app.total_days
            else:
                balance.pending -= leave_app.total_days
            
            balance.update_balance()
        
        LeaveAudit.objects.create(
            leave_application=leave_app,
            action='CANCEL',
            new_value={'status': 'CANCELLED'},
            performed_by=to_uuid(user.id),
            performed_by_name=user.email,
            performed_by_role=user.role,
            reason=serializer.validated_data['cancellation_reason']
        )
        
        send_leave_event('leave_application_cancelled', {
            'leave_application_id': str(leave_app.id),
            'employee_id': str(leave_app.employee_id),
            'cancelled_by': str(user.id),
            'reason': serializer.validated_data['cancellation_reason'],
            'tenant_id': str(leave_app.tenant_id)
        })
        
        return Response({
            'message': 'Leave cancelled successfully',
            'status': 'CANCELLED'
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='my-leaves')
    def my_leaves(self, request):
        user = request.user
        employee_id = to_uuid(user.id)
        
        leaves = LeaveApplication.objects.filter(
            employee_id=employee_id
        ).order_by('-applied_at')
        
        serializer = self.get_serializer(leaves, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request):
        user = request.user
        
        pending_leaves = LeaveApplication.objects.filter(
            status='PENDING',
            approvals__approver_id=to_uuid(user.id),
            approvals__step_number=models.F('current_approval_step'),
            approvals__status='PENDING'
        ).distinct()
        
        serializer = self.get_serializer(pending_leaves, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], url_path='audit-history')
    def audit_history(self, request, pk=None):
        leave_app = self.get_object()
        audits = leave_app.audit_logs.all()
        
        serializer = LeaveAuditSerializer(audits, many=True)
        return Response(serializer.data)
    
    def _calculate_tenure_months(self, joining_date):
        if not joining_date:
            return 0
        if isinstance(joining_date, str):
            joining_date = datetime.strptime(joining_date, '%Y-%m-%d').date()
        delta = date.today() - joining_date
        return delta.days // 30
    
    def _calculate_tenure_years(self, joining_date):
        return self._calculate_tenure_months(joining_date) // 12
    
    def _get_monthly_leave_count(self, employee_id, leave_type):
        today = date.today()
        first_day = today.replace(day=1)
        
        count = LeaveApplication.objects.filter(
            employee_id=employee_id,
            leave_type=leave_type,
            status='APPROVED',
            start_date__gte=first_day,
            start_date__lte=today
        ).count()
        
        return count


class LeaveBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LeaveBalanceSerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        if user.role in ['HR', 'ADMIN', 'HR_MANAGER']:
            return LeaveBalance.objects.filter(tenant_id=tenant_id)
        else:
            return LeaveBalance.objects.filter(
                tenant_id=tenant_id,
                employee_id=to_uuid(user.id)
            )
    
    @action(detail=False, methods=['get'], url_path='my-balance')
    def my_balance(self, request):
        user = request.user
        employee_id = to_uuid(user.id)
        current_year = date.today().year
        
        balances = LeaveBalance.objects.filter(
            employee_id=employee_id,
            year=current_year
        )
        
        serializer = self.get_serializer(balances, many=True)
        return Response(serializer.data)


class LeaveCommentViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveCommentSerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        return LeaveComment.objects.filter(
            leave_application__tenant_id=tenant_id
        ).filter(
            Q(leave_application__employee_id=to_uuid(user.id)) |
            Q(leave_application__approvals__approver_id=to_uuid(user.id)) |
            Q(commented_by=to_uuid(user.id))
        ).distinct()
    
    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(
            commented_by=to_uuid(user.id),
            commented_by_name=user.email,
            commented_by_role=user.role
        )


class HolidayViewSet(viewsets.ModelViewSet):
    serializer_class = HolidaySerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        return Holiday.objects.filter(tenant_id=tenant_id)
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsHROrAdmin()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(tenant_id=to_uuid(user.tenant_id))