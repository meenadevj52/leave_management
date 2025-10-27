from rest_framework import serializers
from ..models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "user_uuid",
            'tenant_id',
            'username',
            'email',
            'first_name',
            'last_name',
            'phone_number'
        ]
