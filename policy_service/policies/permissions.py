from rest_framework.permissions import BasePermission

class IsHROrAdmin(BasePermission):

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        # Check for allowed roles
        return getattr(user, "role", "") in ["HR", "ADMIN", "CHRO"]
