from rest_framework import serializers
from .models import Employee, EmployeeDocument
from decimal import Decimal
import uuid


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    tenure_months = serializers.ReadOnlyField()
    tenure_years = serializers.ReadOnlyField()
    manager_name = serializers.SerializerMethodField()
    department_head_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = '__all__'
        read_only_fields = (
            'id', 'tenant_id', 'created_at', 'updated_at', 
            'created_by', 'updated_by', 'full_name', 
            'tenure_months', 'tenure_years'
        )
    
    def get_manager_name(self, obj):
        return obj.manager.full_name if obj.manager else None
    
    def get_department_head_name(self, obj):
        return obj.department_head.full_name if obj.department_head else None
    
    def validate(self, data):
        # Manager cannot be self
        if self.instance and 'manager' in data and data.get('manager') is not None:
            mgr = data.get('manager')
            mgr_id = None
            # mgr may be an Employee instance or a UUID/str
            if hasattr(mgr, 'id'):
                mgr_id = mgr.id
            else:
                # could be UUID or str
                try:
                    from uuid import UUID
                    mgr_id = UUID(str(mgr))
                except Exception:
                    mgr_id = None
            if mgr_id and str(mgr_id) == str(self.instance.id):
                raise serializers.ValidationError({
                    'manager': 'Employee cannot be their own manager'
                })
        
        # Auto-calculate salary_per_day if not provided
        if data.get('monthly_basic_salary') and not data.get('salary_per_day'):
            data['salary_per_day'] = data['monthly_basic_salary'] / Decimal('30')
        
        return data


class EmployeeListSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    manager_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = [
            'id', 'full_name', 'email', 'designation', 'role', 
            'department', 'employment_type', 'manager_name', 
            'is_active', 'joining_date'
        ]
    
    def get_manager_name(self, obj):
        return obj.manager.full_name if obj.manager else None


class EmployeeDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    tenure_months = serializers.ReadOnlyField()
    tenure_years = serializers.ReadOnlyField()
    is_on_probation = serializers.ReadOnlyField()
    probation_end_date = serializers.ReadOnlyField()
    
    manager_details = serializers.SerializerMethodField()
    department_head_details = serializers.SerializerMethodField()
    subordinates_count = serializers.SerializerMethodField()
    manager_chain = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = '__all__'
    
    def get_manager_details(self, obj):
        if obj.manager:
            return {
                'id': str(obj.manager.id),
                'full_name': obj.manager.full_name,
                'designation': obj.manager.designation,
                'email': obj.manager.email,
                'department': obj.manager.department
            }
        return None
    
    def get_department_head_details(self, obj):
        if obj.department_head:
            return {
                'id': str(obj.department_head.id),
                'full_name': obj.department_head.full_name,
                'designation': obj.department_head.designation,
                'email': obj.department_head.email
            }
        return None
    
    def get_subordinates_count(self, obj):
        return obj.subordinates.filter(is_active=True).count()
    
    def get_manager_chain(self, obj):
        """Get the complete reporting hierarchy."""
        chain = []
        for manager in obj.get_manager_chain():
            chain.append({
                'id': str(manager.id),
                'full_name': manager.full_name,
                'designation': manager.designation,
                'role': manager.role
            })
        return chain


class EmployeeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            'first_name', 'last_name', 'email', 'phone', 
            'designation', 'role', 'department', 
            'manager', 'department_head',
            'joining_date', 'employment_type', 
            'birth_date', 'gender', 'nid',
            'monthly_basic_salary', 'monthly_gross_salary',
            'is_permanent'
        ]
    
    def validate(self, data):
        # Ensure required fields for leave service
        if not data.get('designation'):
            raise serializers.ValidationError({'designation': 'Designation is required'})
        
        if not data.get('department'):
            raise serializers.ValidationError({'department': 'Department is required'})
        
        return data


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    
    class Meta:
        model = EmployeeDocument
        fields = '__all__'
        read_only_fields = ('id', 'uploaded_at', 'uploaded_by')
    
    def get_employee_name(self, obj):
        return obj.employee.full_name