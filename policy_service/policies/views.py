import uuid
import os
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Policy, PolicyAudit
from .serializers import PolicySerializer, PolicyAuditSerializer
from .permissions import IsHROrAdmin
from .authentication import AuthServiceTokenAuthentication
from .tasks import send_policy_event
from .rule_parser import RuleParser, PolicyHelper


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


def clean_policy_data(policy):
    data = {}
    for field in policy._meta.get_fields():
        if field.many_to_many:
            data[field.name] = list(getattr(policy, field.name).values_list('id', flat=True))
        elif field.one_to_many or (field.one_to_one and field.auto_created):
            continue
        else:
            value = getattr(policy, field.name, None)
            if isinstance(value, uuid.UUID):
                value = str(value)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            data[field.name] = value
    return data


class PolicyViewSet(viewsets.ModelViewSet):
    serializer_class = PolicySerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated, IsHROrAdmin]

    def get_queryset(self):
        tenant_id = to_uuid(getattr(self.request.user, "tenant_id", None))
        if not tenant_id:
            return Policy.objects.none()
        return Policy.objects.filter(tenant_id=tenant_id)

    def perform_create(self, serializer):
        """Create a new policy with tenant isolation."""
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        policy = serializer.save(
            tenant_id=tenant_id,
            created_by=to_uuid(user.id),
            updated_by=to_uuid(user.id)
        )
        
        PolicyAudit.objects.create(
            policy=policy,
            new_value=clean_policy_data(policy),
            update_type="CREATE",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(user.id),
            initiator_role=user.role,
            initiator_name=getattr(user, "username", "")
        )
        send_policy_event("policy_created", str(policy.id))


    @action(detail=True, methods=['post'], url_path='approve')
    @transaction.atomic
    def approve(self, request, pk=None):
        policy = self.get_object()
        user = request.user

        if policy.status != 'PENDING_APPROVAL':
            raise ValidationError(f"Policy is not awaiting approval. Current status: {policy.status}")

        try:
            required_role = policy.approval_route[policy.current_approval_step]
        except IndexError:
            raise ValidationError("Approval route is misconfigured or already complete.")

        if user.role != required_role:
            raise PermissionDenied(
                f"User role '{user.role}' cannot approve at this step. Required role: '{required_role}'."
            )

        policy.current_approval_step += 1

        if policy.current_approval_step >= len(policy.approval_route):
            policy.status = "ACTIVE"
            policy.is_active = True

            Policy.objects.filter(
                tenant_id=policy.tenant_id,
                policy_type=policy.policy_type,
                is_active=True
            ).exclude(id=policy.id).update(is_active=False, status="SUPERSEDED")

            event_name = "policy_approved"
        else:
            policy.status = "PENDING_APPROVAL"
            event_name = "policy_awaiting_approval"

        policy.updated_by = to_uuid(user.id)
        policy.save()

        PolicyAudit.objects.create(
            policy=policy,
            new_value=clean_policy_data(policy),
            update_type="APPROVE",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(user.id),
            initiator_role=user.role,
            initiator_name=getattr(user, "username", ""),
            comment=f"Approved at step {policy.current_approval_step - 1}"
        )

        send_policy_event(event_name, str(policy.id))

        return Response({
            "status": policy.status,
            "message": f"Approval step by '{user.role}' successful.",
            "current_step": policy.current_approval_step,
            "total_steps": len(policy.approval_route)
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject')
    @transaction.atomic
    def reject(self, request, pk=None):
        policy = self.get_object()
        user = request.user

        if user.role not in ["HR_MANAGER", "ADMIN", "CHRO", "HR"]:
            raise PermissionDenied("Only HR/Admin/CHRO can reject policies.")

        if policy.status not in ['PENDING_APPROVAL']:
            raise ValidationError(f"Cannot reject policy with status: {policy.status}")

        reason = request.data.get('reason', 'No reason provided')

        policy.status = "REJECTED"
        policy.is_active = False
        policy.updated_by = to_uuid(user.id)
        policy.save()

        PolicyAudit.objects.create(
            policy=policy,
            old_value=None,
            new_value=clean_policy_data(policy),
            update_type="REJECT",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(user.id),
            initiator_role=user.role,
            initiator_name=getattr(user, "username", ""),
            reason=reason,
            comment=request.data.get('comment', '')
        )

        send_policy_event("policy_rejected", str(policy.id))

        return Response({
            "status": "rejected",
            "reason": reason
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='test-validation')
    def test_validation(self, request, pk=None):
        policy = self.get_object()

        leave_request = request.data.get('leave_request', {})
        employee = request.data.get('employee', {})
        context = request.data.get('context', {})

        is_valid, errors, actions = RuleParser.validate_leave_request(
            policy, leave_request, {**context, **employee}
        )

        approval_chain = RuleParser.get_approval_chain(policy, employee)

        return Response({
            'is_valid': is_valid,
            'errors': errors,
            'actions_to_execute': actions,
            'approval_chain': approval_chain,
            'policy': {
                'id': str(policy.id),
                'name': policy.policy_name,
                'version': policy.version
            }
        })

    @action(detail=True, methods=['get'], url_path='audit-history')
    def audit_history(self, request, pk=None):
        policy = self.get_object()
        audits = policy.audits.all().order_by('-timestamp_utc')

        serializer = PolicyAuditSerializer(audits, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='upload-attachment')
    def upload_attachment(self, request, pk=None):
        policy = self.get_object()

        if 'file' not in request.FILES:
            return Response(
                {"error": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = request.FILES['file']

        if uploaded_file.size > 10 * 1024 * 1024:
            return Response(
                {"error": "File size exceeds 10MB limit"},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_extensions = ['.pdf', '.docx', '.txt', '.doc']
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        if file_ext not in allowed_extensions:
            return Response(
                {"error": f"File type not allowed. Allowed: {', '.join(allowed_extensions)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        file_name = f"policy_{policy.id}_{uploaded_file.name}"
        file_path = default_storage.save(
            f"policy_attachments/{file_name}",
            ContentFile(uploaded_file.read())
        )

        if not isinstance(policy.attachments, list):
            policy.attachments = []

        policy.attachments.append({
            'filename': uploaded_file.name,
            'path': file_path,
            'size': uploaded_file.size,
            'uploaded_at': timezone.now().isoformat(),
            'uploaded_by': str(request.user.id)
        })

        policy.save()

        PolicyAudit.objects.create(
            policy=policy,
            old_value=None,
            new_value={'attachment': policy.attachments[-1]},
            update_type="ATTACHMENT_UPLOAD",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(request.user.id),
            initiator_role=request.user.role,
            initiator_name=getattr(request.user, "username", "")
        )

        return Response({
            "message": "File uploaded successfully",
            "attachment": policy.attachments[-1]
        }, status=status.HTTP_200_OK)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        policy = self.get_object()

        if policy.status == 'ACTIVE':
            return Response(
                {"error": "Cannot delete an active policy. Please create a new version or reject it first."},
                status=status.HTTP_400_BAD_REQUEST
            )

        policy.status = 'INACTIVE'
        policy.is_active = False
        policy.save()

        PolicyAudit.objects.create(
            policy=policy,
            old_value=None,
            new_value=clean_policy_data(policy),
            update_type="DELETE",
            timestamp_utc=timezone.now(),
            initiator_id=to_uuid(request.user.id),
            initiator_role=request.user.role,
            initiator_name=getattr(request.user, "username", "")
        )

        send_policy_event("policy_deleted", str(policy.id))

        return Response(
            {"message": "Policy deactivated successfully"},
            status=status.HTTP_204_NO_CONTENT
        )