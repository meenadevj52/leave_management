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
from .services.approval_service import ApprovalChainService
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
        
        print(f"\nget_queryset called for user: {user.email} (role: {user.role})")
        
        queryset = LeaveApplication.objects.filter(tenant_id=tenant_id)
        
        privileged_roles = ['HR', 'ADMIN', 'HR_MANAGER', 'CHRO', 'CFO', 'CEO']
        
        if user.role in privileged_roles:
            print(f"{user.role} has full access - returning all {queryset.count()} leaves")
            return queryset
        
        try:
            employee = EmployeeServiceClient.get_employee_by_email(user.email)
            
            if not employee:
                print(f"Employee not found for email: {user.email}")
                return queryset.none()
            
            employee_id = to_uuid(employee.get('id'))
            print(f"Employee ID fetched: {employee_id}")
            
            filtered_queryset = queryset.filter(
                Q(employee_id=employee_id) |
                Q(approvals__approver_id=employee_id)
            ).distinct()
            
            print(f"Returning {filtered_queryset.count()} leaves for employee")
            return filtered_queryset
            
        except Exception as e:
            print(f"Error in get_queryset: {e}")
            import traceback
            traceback.print_exc()
            

            return queryset.none()
    
    @transaction.atomic
    def perform_create(self, serializer):

        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        user_email = user.email
        
        print("\n" + "="*80)
        print("CREATING LEAVE APPLICATION")
        print("="*80)
        
        print(f"Fetching employee details for: {user_email}")
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
        print(f"Employee found: {employee.get('full_name')} (ID: {employee_id})")
        
        leave_type = serializer.validated_data['leave_type']
        print(f"\nFetching active {leave_type} policy...")
        policy = PolicyServiceClient.get_active_policy(tenant_id, leave_type)
        
        if not policy:
            raise ValidationError({
                'error': f'No active policy found for {leave_type} leave type.'
            })
        
        print(f"Policy found: {policy.get('policy_name')} (v{policy.get('version')})")
        print(f"Approval Route from Policy: {policy.get('approval_route', [])}")
        
        start_date = serializer.validated_data['start_date']
        end_date = serializer.validated_data['end_date']
        is_half_day = serializer.validated_data.get('is_half_day', False)
        
        print(f"\nCalculating leave days: {start_date} to {end_date}")
        total_days, holidays_count = LeaveValidationService.calculate_leave_days(
            start_date, end_date, is_half_day, tenant_id
        )
        print(f"Total leave days: {total_days} (Holidays excluded: {holidays_count})")
        
        print(f"\nChecking for overlapping leaves...")
        if LeaveValidationService.check_leave_overlap(employee_id, start_date, end_date):
            raise ValidationError({
                'error': 'You have overlapping leave applications for these dates.'
            })
        print(f"No overlapping leaves found")
        
        current_year = date.today().year
        print(f"\nFetching/Creating leave balance for {leave_type} ({current_year})...")
        balance, created = LeaveValidationService.get_or_create_balance(
            tenant_id, employee_id, leave_type, current_year,
            total_allocated=policy.get('entitlement', {}).get('base_days', 0)
        )

        if created:
            print(f"Created new leave balance: {leave_type} = {balance.total_allocated} days")
        else:
            print(f"Using existing balance: {leave_type} = {balance.available}/{balance.total_allocated} days")
        
        employee_data = {
            'id': str(employee_id),
            'role': employee.get('designation', employee.get('role')),
            'department': employee.get('department'),
            'manager_id': employee.get('manager_id'),
            'tenure_months': self._calculate_tenure_months(employee.get('joining_date')),
            'tenure_years': self._calculate_tenure_years(employee.get('joining_date')),
            'employment_type': employee.get('employment_type'),
            'full_name': employee.get('full_name', user_email),
            'email': employee.get('email', user_email)
        }
        
        print(f"\nEmployee Context:")
        print(f"   Department: {employee_data.get('department')}")
        print(f"   Manager ID: {employee_data.get('manager_id')}")
        print(f"   Employment Type: {employee_data.get('employment_type')}")
        
        leave_request_data = {
            'leave_type': leave_type,
            'leave_days': float(total_days),
            'start_date': str(start_date),
            'end_date': str(end_date),
            'request_type': serializer.validated_data.get('request_type', 'leave'),
            'employment_type': employee.get('employment_type'),
            'documentation_provided': len(serializer.validated_data.get('attachments', [])) > 0
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
        
        approval_route = policy.get('approval_route', [])
        if not approval_route:
            raise ValidationError({
                'error': 'No approval route configured in policy',
                'detail': 'Please contact HR to configure approval workflow for this leave type'
            })
        
        print(f"\nBuilding approval chain from policy route: {approval_route}")
        approval_chain = ApprovalChainService.build_approval_chain(
            tenant_id, employee_data, approval_route
        )
        
        print(f"\nApproval Chain Built:")
        for step in approval_chain:
            print(f"   Step {step['step']}: {step['role']} → {step.get('approver_name', 'Not Assigned')}")
        
        if not ApprovalChainService.validate_approval_chain(approval_chain):
            raise ValidationError({
                'error': 'Invalid approval chain',
                'detail': 'No valid approvers found in approval chain. Please contact HR.',
                'approval_chain': approval_chain
            })
        
        print(f"\nValidating against policy rules...")
        validation_result = self._validate_against_policy(
            policy, leave_request_data, employee_data, context
        )
        
        if not validation_result['is_valid']:
            errors = [error['reason'] for error in validation_result['errors']]
            print(f"Validation failed: {errors}")
            raise ValidationError({
                'error': 'Leave request validation failed',
                'reasons': errors,
                'details': validation_result['errors']
            })
        print(f"Policy validation passed")
        
        if serializer.validated_data.get('request_type', 'leave') == 'leave':
            print(f"\nChecking balance: Available={balance.available}, Requested={total_days}")
            if not LeaveValidationService.check_sufficient_balance(
                employee_id, leave_type, total_days, current_year
            ):
                raise ValidationError({
                    'error': 'Insufficient leave balance',
                    'available': float(balance.available),
                    'requested': float(total_days)
                })
            print(f"Sufficient balance available")
        
        encashment_amount = Decimal('0')
        if serializer.validated_data.get('request_type') == 'encashment':
            encashment_days = Decimal(str(serializer.validated_data.get('encashment_days', 0)))
            salary_per_day = Decimal(str(employee.get('salary_per_day', 0)))
            
            print(f"\nCalculating encashment: {encashment_days} days {salary_per_day}/day")
            encashment_result = LeaveValidationService.calculate_encashment(
                policy, balance.available, encashment_days, salary_per_day
            )
            
            if not encashment_result['allowed']:
                raise ValidationError({'error': encashment_result['reason']})
            
            encashment_amount = Decimal(str(encashment_result['amount']))
            print(f"Encashment calculated: {encashment_amount}")
        
        print(f"\nCreating leave application in database...")
        leave_app = serializer.save(
            tenant_id=tenant_id,
            employee_id=employee_id,
            total_days=total_days,
            policy_id=to_uuid(policy['id']),
            policy_version=policy['version'],
            approval_chain=approval_chain,
            status='PENDING',
            current_approval_step=0,
            created_by=employee_id,
            updated_by=employee_id,
            encashment_amount=encashment_amount
        )
        print(f"Leave application created: {leave_app.id}")
        
        print(f"\nCreating approval steps...")
        for approval_step in approval_chain:
            LeaveApproval.objects.create(
                leave_application=leave_app,
                step_number=approval_step['step'],
                approver_role=approval_step['role'],
                approver_id=to_uuid(approval_step['user_id']) if approval_step.get('user_id') else None,
                status='PENDING'
            )
            
            print(f" Step {approval_step['step']}: {approval_step['role']} → {approval_step.get('approver_name', 'Not Assigned')}")
        
        if serializer.validated_data.get('request_type', 'leave') == 'leave':
            print(f"\nUpdating leave balance (adding {total_days} to pending)...")
            balance.pending += total_days
            balance.update_balance()
            print(f"Balance updated: Available={balance.available}, Pending={balance.pending}")
        
        print(f"\nCreating audit log...")
        LeaveAudit.objects.create(
            leave_application=leave_app,
            action='CREATE',
            new_value=clean_leave_data(leave_app),
            performed_by=employee_id,
            performed_by_name=employee.get('full_name', user.email),
            performed_by_role=user.role,
            reason='Leave application submitted'
        )
        print(f"Audit log created")
        
        print(f"\nSending Kafka event...")
        send_leave_event('leave_application_created', {
            'leave_application_id': str(leave_app.id),
            'employee_id': str(employee_id),
            'leave_type': leave_type,
            'start_date': str(start_date),
            'end_date': str(end_date),
            'total_days': float(total_days),
            'status': 'PENDING',
            'tenant_id': str(tenant_id),
            'approval_chain': approval_chain,
            'first_approver': approval_chain[0] if approval_chain else None
        })
        print(f"Kafka event sent")
        
        print("\n" + "="*80)
        print("LEAVE APPLICATION CREATED SUCCESSFULLY")
        print("="*80 + "\n")
    
    def _validate_against_policy(self, policy, leave_data, employee_data, context):

        errors = []
        
        if leave_data['leave_days'] > context['accrual_balance']:
            errors.append({
                'condition_id': 'balance_check',
                'reason': f"Insufficient leave balance. Available: {context['accrual_balance']}, Requested: {leave_data['leave_days']}"
            })
        
        if employee_data.get('employment_type') == 'Probation' and leave_data['leave_type'] in ['Annual', 'Casual']:
            errors.append({
                'condition_id': 'probation_check',
                'reason': 'Annual and Casual leave not allowed during probation period'
            })
        
        required_notice = context.get('notice_period', 0)
        actual_notice = context.get('leave_request_notice_days', 0)
        
        if actual_notice < required_notice:
            errors.append({
                'condition_id': 'notice_period_check',
                'reason': f'Leave must be applied at least {required_notice} days in advance. Applied {actual_notice} days before.'
            })
        
        if leave_data['leave_type'] == 'Sick' and leave_data['leave_days'] > 3:
            if not leave_data.get('documentation_provided'):
                errors.append({
                    'condition_id': 'documentation_required',
                    'reason': 'Medical certificate required for sick leave > 3 days'
                })
        
        monthly_limit = context.get('monthly_limit', 0)
        if monthly_limit > 0:
            prior_count = context.get('prior_leave_count', 0)
            if prior_count >= monthly_limit:
                errors.append({
                    'condition_id': 'monthly_limit',
                    'reason': f'Monthly limit of {monthly_limit} leaves already reached'
                })
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'actions': []
        }
    
    @action(detail=True, methods=['post'], url_path='approve')
    @transaction.atomic

    def approve_leave(self, request, pk=None):
        leave_app = self.get_object()
        user = request.user
        user_email = user.email
        
        print("\n" + "="*80)
        print(f"APPROVAL REQUEST for Leave Application: {leave_app.id}")
        print("="*80)
        
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
        employee_role = employee.get('role')
        
        print(f"Approver: {employee.get('full_name')} (ID: {employee_id})")
        print(f"Role: {employee_role}")
        print(f"Current Approval Step: {leave_app.current_approval_step}")
        print(f"Total Steps: {leave_app.approvals.count()}")
        
        print("\nALL APPROVAL STEPS:")
        for approval in leave_app.approvals.all().order_by('step_number'):
            print(f"   Step {approval.step_number}:")
            print(f"      Role: {approval.approver_role}")
            print(f"      Approver ID: {approval.approver_id}")
            print(f"      Status: {approval.status}")
            if approval.approver_id:
                print(f"      ID Match: {str(approval.approver_id) == str(employee_id)}")
        
        print(f"\nLooking for approval at step {leave_app.current_approval_step}")
        
        try:
            current_approval = leave_app.approvals.get(
                step_number=leave_app.current_approval_step
            )
        except LeaveApproval.DoesNotExist:
            raise ValidationError({
                'error': 'Invalid approval step',
                'detail': f'No approval record found for step {leave_app.current_approval_step}'
            })
        
        print(f"\nCurrent Approval Step Details:")
        print(f"   Required Role: {current_approval.approver_role}")
        print(f"   Assigned Approver ID: {current_approval.approver_id}")
        print(f"   Current Status: {current_approval.status}")
        
        is_authorized = False
        authorization_method = None
        
        if current_approval.approver_id:
            if str(current_approval.approver_id) == str(employee_id):
                is_authorized = True
                authorization_method = "APPROVER_ID_MATCH"
                print(f"Authorized by APPROVER_ID match")
        
        if not is_authorized and employee_role == current_approval.approver_role:
            is_authorized = True
            authorization_method = "ROLE_MATCH"
            print(f"Authorized by ROLE match ({employee_role} == {current_approval.approver_role})")
        
        if not is_authorized and employee_role in ['HR', 'ADMIN', 'HR_MANAGER', 'CHRO']:
            is_authorized = True
            authorization_method = "HR_ADMIN_OVERRIDE"
            print(f"Authorized as HR/ADMIN override")
        
        if not is_authorized:
            print(f"\nAUTHORIZATION FAILED")
            print(f"   User ID: {employee_id}")
            print(f"   User Role: {employee_role}")
            print(f"   Required Approver ID: {current_approval.approver_id}")
            print(f"   Required Role: {current_approval.approver_role}")
            
            print(f"\nAvailable approvals at step {leave_app.current_approval_step}:")
            step_approvals = leave_app.approvals.filter(step_number=leave_app.current_approval_step)
            for appr in step_approvals:
                print(f"   Approver ID: {appr.approver_id}")
                print(f"   Role: {appr.approver_role}")
                print(f"   Status: {appr.status}")
            
            raise PermissionDenied({
                'error': 'You are not authorized to approve this leave application at this step.',
                'detail': {
                    'your_role': employee_role,
                    'required_role': current_approval.approver_role,
                    'your_id': str(employee_id),
                    'required_id': str(current_approval.approver_id) if current_approval.approver_id else None
                }
            })
        
        print(f"Authorization successful via: {authorization_method}")
        
        if current_approval.status != 'PENDING':
            raise ValidationError({
                'error': f'This approval step is already {current_approval.status}.',
                'current_status': current_approval.status
            })
        
        serializer = LeaveApplicationApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        comments = serializer.validated_data.get('comments', '')
        
        print(f"\nAction: {action.upper()}")
        print(f"Comments: {comments if comments else '(none)'}")
        
        if action == 'approve':
            current_approval.status = 'APPROVED'
            current_approval.comments = comments
            current_approval.actioned_at = timezone.now()
            current_approval.save()
            print(f"Step {current_approval.step_number} approved by {employee.get('full_name')}")
            
            leave_app.current_approval_step += 1
            
            if leave_app.current_approval_step >= leave_app.approvals.count():
                leave_app.status = 'APPROVED'
                leave_app.approved_at = timezone.now()
                
                print(f"\nALL APPROVAL STEPS COMPLETED - LEAVE APPROVED!")
                
                if leave_app.request_type == 'leave':
                    try:
                        balance = LeaveBalance.objects.get(
                            employee_id=leave_app.employee_id,
                            leave_type=leave_app.leave_type,
                            year=date.today().year
                        )
                        balance.pending -= leave_app.total_days
                        balance.used += leave_app.total_days
                        balance.update_balance()
                        print(f" Balance updated:")
                        print(f"   Used: {balance.used}")
                        print(f"   Available: {balance.available}")
                        print(f"   Pending: {balance.pending}")
                    except LeaveBalance.DoesNotExist:
                        print(f"Warning: Leave balance not found for {leave_app.leave_type}")
                
                event_name = 'leave_application_approved'
                notification_message = f'Your {leave_app.leave_type} leave has been fully approved'
            else:
                print(f"\nMoving to next approval step: {leave_app.current_approval_step}")
                next_approval = leave_app.approvals.filter(
                    step_number=leave_app.current_approval_step
                ).first()
                
                if next_approval:
                    print(f"Next approver:")
                    print(f"Role: {next_approval.approver_role}")
                    print(f"Approver ID: {next_approval.approver_id}")
                
                event_name = 'leave_application_step_approved'
                notification_message = f'Your {leave_app.leave_type} leave has been approved at step {current_approval.step_number}'
            
            leave_app.save()
            
            LeaveAudit.objects.create(
                leave_application=leave_app,
                action='APPROVE_STEP',
                old_value={'status': 'PENDING', 'step': current_approval.step_number},
                new_value={'status': 'APPROVED', 'step': current_approval.step_number},
                performed_by=employee_id,
                performed_by_name=employee.get('full_name', user.email),
                performed_by_role=employee_role,
                reason=comments or f'Approved by {employee.get("full_name")}'
            )
            print(f"Audit log created")
            
            send_leave_event(event_name, {
                'leave_application_id': str(leave_app.id),
                'employee_id': str(leave_app.employee_id),
                'status': leave_app.status,
                'approved_by': str(employee_id),
                'approved_by_name': employee.get('full_name'),
                'approved_by_role': employee_role,
                'step_number': current_approval.step_number,
                'total_steps': leave_app.approvals.count(),
                'current_step': leave_app.current_approval_step,
                'tenant_id': str(leave_app.tenant_id),
                'leave_type': leave_app.leave_type,
                'start_date': str(leave_app.start_date),
                'end_date': str(leave_app.end_date),
                'total_days': float(leave_app.total_days),
                'notification_message': notification_message
            })
            print(f"Kafka event sent: {event_name}")
            
            print("="*80 + "\n")
            
            return Response({
                'success': True,
                'message': 'Leave application approved successfully',
                'status': leave_app.status,
                'current_step': leave_app.current_approval_step,
                'total_steps': leave_app.approvals.count(),
                'fully_approved': leave_app.status == 'APPROVED',
                'approval_details': {
                    'approved_by': employee.get('full_name'),
                    'approved_at': current_approval.actioned_at.isoformat(),
                    'comments': comments
                }
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
            
            print(f"\nLEAVE APPLICATION REJECTED")
            print(f" Rejected at step: {current_approval.step_number}")
            print(f"Rejected by: {employee.get('full_name')}")
            print(f"Reason: {comments}")
            
            if leave_app.request_type == 'leave':
                try:
                    balance = LeaveBalance.objects.get(
                        employee_id=leave_app.employee_id,
                        leave_type=leave_app.leave_type,
                        year=date.today().year
                    )
                    balance.pending -= leave_app.total_days
                    balance.update_balance()
                    print(f"Balance restored:")
                    print(f"Pending: {balance.pending}")
                    print(f"Available: {balance.available}")
                except LeaveBalance.DoesNotExist:
                    print(f"Warning: Leave balance not found")
            
            LeaveAudit.objects.create(
                leave_application=leave_app,
                action='REJECT',
                old_value={'status': 'PENDING'},
                new_value={'status': 'REJECTED'},
                performed_by=employee_id,
                performed_by_name=employee.get('full_name', user.email),
                performed_by_role=employee_role,
                reason=comments or f'Rejected by {employee.get("full_name")}'
            )
            print(f"Audit log created")
            
            send_leave_event('leave_application_rejected', {
                'leave_application_id': str(leave_app.id),
                'employee_id': str(leave_app.employee_id),
                'status': 'REJECTED',
                'rejected_by': str(employee_id),
                'rejected_by_name': employee.get('full_name'),
                'rejected_by_role': employee_role,
                'step_number': current_approval.step_number,
                'reason': comments,
                'tenant_id': str(leave_app.tenant_id),
                'leave_type': leave_app.leave_type,
                'start_date': str(leave_app.start_date),
                'end_date': str(leave_app.end_date),
                'notification_message': f'Your {leave_app.leave_type} leave has been rejected'
            })
            print(f"Kafka event sent: leave_application_rejected")
            
            print("="*80 + "\n")
            
            return Response({
                'success': True,
                'message': 'Leave application rejected',
                'status': 'REJECTED',
                'reason': comments,
                'rejection_details': {
                    'rejected_by': employee.get('full_name'),
                    'rejected_at': current_approval.actioned_at.isoformat(),
                    'comments': comments
                }
            }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], url_path='cancel')
    @transaction.atomic
    def cancel_leave(self, request, pk=None):
        """Cancel a leave application (employee self-cancellation)."""
        leave_app = self.get_object()
        user = request.user
        user_email = user.email
        
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
        
        if str(leave_app.employee_id) != str(employee_id):
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
        leave_app.cancelled_by = employee_id
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
            performed_by=employee_id,
            performed_by_name=employee.get('full_name', user.email),
            performed_by_role=user.role,
            reason=serializer.validated_data['cancellation_reason']
        )
        
        send_leave_event('leave_application_cancelled', {
            'leave_application_id': str(leave_app.id),
            'employee_id': str(leave_app.employee_id),
            'cancelled_by': str(employee_id),
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
        user_email = user.email
        
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
        
        leaves = LeaveApplication.objects.filter(
            employee_id=employee_id
        ).order_by('-applied_at')
        
        serializer = self.get_serializer(leaves, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request):
        user = request.user
        user_email = user.email
        
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
        
        pending_leaves = LeaveApplication.objects.filter(
            status='PENDING',
            approvals__approver_id=employee_id,
            approvals__step_number=F('current_approval_step'),
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
        
        if user.role in ['HR', 'ADMIN', 'CHRO']:
            return LeaveBalance.objects.filter(tenant_id=tenant_id)
        else:
            return LeaveBalance.objects.filter(
                tenant_id=tenant_id,
                employee_id=to_uuid(user.id)
            )
    
    @action(detail=False, methods=['get'], url_path='my-balance')
    def my_balance(self, request):
        user = request.user
        user_email = user.email
        
        employee = EmployeeServiceClient.get_employee_by_email(user_email)
        if not employee:
            raise ValidationError({
                'error': 'Employee details not found',
                'detail': f'No employee found with email: {user_email}'
            })
        
        employee_id = to_uuid(employee.get('id'))
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
        return Holiday.objects.filter(tenant_id=tenant_id).order_by('date')
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsHROrAdmin()]
        return [IsAuthenticated()]
    
    def perform_create(self, serializer):
        """Create holiday with duplicate check."""
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        date = serializer.validated_data.get('date')
        
        existing = Holiday.objects.filter(
            tenant_id=tenant_id,
            date=date
        ).first()
        
        if existing:
            raise ValidationError({
                'error': 'Holiday already exists for this date',
                'date': str(date),
                'existing_holiday': {
                    'id': str(existing.id),
                    'name': existing.name,
                    'date': str(existing.date),
                    'is_optional': existing.is_optional
                }
            })
        
        serializer.save(tenant_id=tenant_id)
    
    def perform_update(self, serializer):
        """Update holiday with duplicate check."""
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        instance = self.get_object()
        new_date = serializer.validated_data.get('date', instance.date)
        
        if new_date != instance.date:
            existing = Holiday.objects.filter(
                tenant_id=tenant_id,
                date=new_date
            ).exclude(id=instance.id).first()
            
            if existing:
                raise ValidationError({
                    'error': 'Holiday already exists for this date',
                    'date': str(new_date),
                    'existing_holiday': {
                        'id': str(existing.id),
                        'name': existing.name
                    }
                })
        
        serializer.save()
    
    @action(detail=False, methods=['post'], url_path='bulk-create', permission_classes=[IsAuthenticated, IsHROrAdmin])
    def bulk_create(self, request):
        user = request.user
        tenant_id = to_uuid(user.tenant_id)
        holidays_data = request.data.get('holidays', [])
        
        if not holidays_data:
            return Response(
                {'error': 'No holidays provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created = []
        skipped = []
        errors = []
        
        for holiday_data in holidays_data:
            try:
                date_val = holiday_data.get('date')
                name = holiday_data.get('name')
                is_optional = holiday_data.get('is_optional', False)
                
               
                existing = Holiday.objects.filter(
                    tenant_id=tenant_id,
                    date=date_val
                ).first()
                
                if existing:
                    skipped.append({
                        'name': name,
                        'date': date_val,
                        'reason': f'Holiday already exists: {existing.name}'
                    })
                    continue
                
              
                holiday = Holiday.objects.create(
                    tenant_id=tenant_id,
                    name=name,
                    date=date_val,
                    is_optional=is_optional
                )
                
                created.append({
                    'id': str(holiday.id),
                    'name': holiday.name,
                    'date': str(holiday.date),
                    'is_optional': holiday.is_optional
                })
                
            except Exception as e:
                errors.append({
                    'holiday': holiday_data,
                    'error': str(e)
                })
        
        return Response({
            'created': len(created),
            'skipped': len(skipped),
            'errors': len(errors),
            'details': {
                'created': created,
                'skipped': skipped,
                'errors': errors
            }
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='year/(?P<year>[0-9]{4})')
    def by_year(self, request, year=None):

        user = request.user
        tenant_id = to_uuid(user.tenant_id)
        
        holidays = Holiday.objects.filter(
            tenant_id=tenant_id,
            date__year=year
        ).order_by('date')
        
        serializer = self.get_serializer(holidays, many=True)
        return Response({
            'year': year,
            'count': holidays.count(),
            'holidays': serializer.data
        })
    
    @action(detail=False, methods=['delete'], url_path='clear-year/(?P<year>[0-9]{4})', permission_classes=[IsAuthenticated, IsHROrAdmin])
    def clear_year(self, request, year=None):

        user = request.user
        tenant_id = to_uuid(user.tenant_id)
        
        deleted_count = Holiday.objects.filter(
            tenant_id=tenant_id,
            date__year=year
        ).delete()[0]
        
        return Response({
            'message': f'Deleted {deleted_count} holidays for year {year}',
            'year': year,
            'deleted_count': deleted_count
        }, status=status.HTTP_200_OK)