import uuid
import json
import time
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
from django.conf import settings
from kafka import KafkaProducer
from django.utils import timezone

from .models import Employee, EmployeeDocument
from .serializers import (
    EmployeeSerializer, EmployeeListSerializer, EmployeeDetailSerializer,
    EmployeeCreateSerializer, EmployeeDocumentSerializer
)
from .permissions import IsHROrAdmin
from .authentication import AuthServiceTokenAuthentication


def get_kafka_producer():
    producer = None
    retry_count = 0
    max_retries = 3
    
    while not producer and retry_count < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print(f"Kafka not ready, retrying in 5s... ({retry_count}/{max_retries})", e)
            time.sleep(5)
            retry_count += 1
    
    return producer


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


class EmployeeViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return EmployeeListSerializer
        elif self.action == 'retrieve':
            return EmployeeDetailSerializer
        elif self.action == 'create':
            return EmployeeCreateSerializer
        return EmployeeSerializer
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        queryset = Employee.objects.filter(tenant_id=tenant_id, is_active=True)
        
        if user.role in ['HR', 'ADMIN', 'CHRO']:
            return queryset
        elif user.role in ['MANAGER', 'DEPARTMENT_HEAD']:
            employee = Employee.objects.filter(
                tenant_id=tenant_id, 
                email=user.email
            ).first()
            
            if employee:
                return queryset.filter(
                    Q(manager=employee) | Q(id=employee.id)
                )
        else:
            return queryset.filter(email=user.email)
        
        return queryset.none()
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsHROrAdmin()]
        return [IsAuthenticated()]
    
        def perform_create(self, serializer):
            """Create employee only if tenant is valid."""
            user = self.request.user
            created_by = to_uuid(user.id)
            role = self.request.data.get('role', 'EMPLOYEE')

            tenant_id = to_uuid(self.request.data.get('tenant_id')) or to_uuid(user.tenant_id)

            if not tenant_id:
                raise PermissionDenied("Tenant ID missing. Cannot create employee.")

            is_valid_tenant = validate_tenant_via_kafka(tenant_id)
            if not is_valid_tenant:
                raise PermissionDenied("Invalid or inactive tenant. Cannot create employee.")

            employee = serializer.save(
                tenant_id=tenant_id,
                created_by=created_by,
                updated_by=created_by,
                role=role
            )

            producer = get_kafka_producer()
            if producer:
                event = {
                    "email": employee.email,
                    "first_name": employee.first_name,
                    "last_name": employee.last_name,
                    "tenant_id": str(tenant_id),
                    "role": employee.role,
                    "default_password": "Password@123"
                }

                try:
                    producer.send("employee_created", event)
                    producer.flush()
                    print(f"Kafka event sent for employee creation: {employee.email}")
                except Exception as e:
                    print(f"Kafka error while sending employee_created event: {e}")
                finally:
                    producer.close()
    
    def perform_update(self, serializer):
        user = self.request.user
        updated_by = to_uuid(user.id)
        
        employee = serializer.save(updated_by=updated_by)
        
        producer = get_kafka_producer()
        
        if producer:
            event = {
                "employee_id": str(employee.id),
                "email": employee.email,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "tenant_id": str(employee.tenant_id),
                "role": employee.role,
                "designation": employee.designation,
                "department": employee.department,
                "updated_by": str(user.id)
            }
            
            try:
                producer.send("employee_updated", event)
                producer.flush()
                print(f"Kafka event sent for employee update: {employee.email}")
            except Exception as e:
                print(f"Kafka error while sending employee_updated event: {e}")
            finally:
                producer.close()
    
    def perform_destroy(self, instance):
        instance.is_active = False
        instance.termination_date = timezone.now().date()
        instance.save()
    
    @action(detail=False, methods=['get'], url_path='me')
    def my_profile(self, request):
        user = request.user
        tenant_id = to_uuid(user.tenant_id)
        
        try:
            employee = Employee.objects.get(
                tenant_id=tenant_id,
                email=user.email
            )
            serializer = EmployeeDetailSerializer(employee)
            return Response(serializer.data)
        except Employee.DoesNotExist:
            return Response(
                {"error": "Employee profile not found"},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'], url_path='subordinates')
    def subordinates(self, request, pk=None):
        employee = self.get_object()
        subordinates = Employee.objects.filter(
            manager=employee,
            is_active=True
        )
        
        serializer = EmployeeListSerializer(subordinates, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='by-department')
    def by_department(self, request):
        tenant_id = to_uuid(request.user.tenant_id)
        department = request.query_params.get('department')
        
        queryset = Employee.objects.filter(
            tenant_id=tenant_id,
            is_active=True
        )
        
        if department:
            queryset = queryset.filter(department=department)
        
        serializer = EmployeeListSerializer(queryset, many=True)
        return Response(serializer.data)


class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeDocumentSerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = to_uuid(user.tenant_id)
        
        queryset = EmployeeDocument.objects.filter(
            employee__tenant_id=tenant_id
        )
        
        if user.role not in ['HR', 'ADMIN', 'CHRO']:
            employee = Employee.objects.filter(
                tenant_id=tenant_id,
                email=user.email
            ).first()
            
            if employee:
                queryset = queryset.filter(employee=employee)
            else:
                return queryset.none()
        
        return queryset
    
    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(uploaded_by=to_uuid(user.id))


class EmployeeCreateView(generics.CreateAPIView):
    serializer_class = EmployeeCreateSerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated, IsHROrAdmin]

    def post(self, request, *args, **kwargs):
        viewset = EmployeeViewSet()
        viewset.request = request
        viewset.format_kwarg = None
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        viewset.perform_create(serializer)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class EmployeeUpdateView(generics.UpdateAPIView):
    serializer_class = EmployeeSerializer
    authentication_classes = [AuthServiceTokenAuthentication]
    permission_classes = [IsAuthenticated, IsHROrAdmin]
    lookup_field = "id"

    def get_queryset(self):
        tenant_id = to_uuid(self.request.user.tenant_id)
        return Employee.objects.filter(tenant_id=tenant_id)

    def perform_update(self, serializer):
        viewset = EmployeeViewSet()
        viewset.request = self.request
        viewset.perform_update(serializer)