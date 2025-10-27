from rest_framework import generics, status,serializers
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate

from .models import User
from .serializers.user_serializer import UserSerializer
from .serializers.register_serializer import RegisterSerializer
from .serializers.login_serializer import LoginSerializer
from .kafka_client import send_tenant_verification_request

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def perform_create(self, serializer):
        tenant_id = self.request.data.get("tenant_id")
        if not tenant_id:
            raise serializers.ValidationError({"tenant_id": "Tenant ID is required"})

        tenant_exists = send_tenant_verification_request(tenant_id)
        if not tenant_exists:
            raise serializers.ValidationError({"tenant_id": "Tenant does not exist"})

        serializer.save(tenant_id=tenant_id)


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        user = authenticate(request, username=email, password=password)
        if user:
            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "Login successful",
                "status": "success",
                "token": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
                "user": UserSerializer(user).data
            })
        return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
