from rest_framework.permissions import BasePermission

class IsEmployee(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsHROrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return getattr(user, "role", "") in ["HR", "ADMIN", "HR_MANAGER"]


class IsApprover(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        for approval in obj.approvals.all():
            if str(approval.approver_id) == str(user.id):
                return True
        return False


class IsOwnerOrApprover(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if str(obj.employee_id) == str(user.id):
            return True
        for approval in obj.approvals.all():
            if str(approval.approver_id) == str(user.id):
                return True
        if user.role in ["HR", "ADMIN", "HR_MANAGER"]:
            return True
        return False