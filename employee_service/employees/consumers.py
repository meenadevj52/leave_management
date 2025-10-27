import json
import time
from kafka import KafkaConsumer, KafkaProducer
from django.conf import settings
from .models import Employee
from .serializers import EmployeeDetailSerializer


KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


def get_kafka_producer():
    producer = None
    retry_count = 0
    max_retries = 5
    
    while not producer and retry_count < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            print("Kafka producer connected")
        except Exception as e:
            print(f"Kafka not ready, retrying... ({retry_count}/{max_retries}): {e}")
            time.sleep(5)
            retry_count += 1
    
    return producer


def serialize_employee(employee):
    return {
        'id': str(employee.id),
        'tenant_id': str(employee.tenant_id),
        'full_name': employee.full_name,
        'first_name': employee.first_name,
        'last_name': employee.last_name,
        'email': employee.email,
        'phone': employee.phone,
        'designation': employee.designation,
        'role': employee.role,
        'department': employee.department,
        'manager_id': str(employee.manager.id) if employee.manager else None,
        'manager_name': employee.manager.full_name if employee.manager else None,
        'department_head_id': str(employee.department_head.id) if employee.department_head else None,
        'employment_type': employee.employment_type,
        'is_permanent': employee.is_permanent,
        'joining_date': str(employee.joining_date),
        'tenure_months': employee.tenure_months,
        'tenure_years': employee.tenure_years,
        'is_on_probation': employee.is_on_probation,
        'salary_per_day': float(employee.salary_per_day),
        'monthly_basic_salary': float(employee.monthly_basic_salary),
        'monthly_gross_salary': float(employee.monthly_gross_salary),
        'is_in_notice_period': employee.is_in_notice_period,
        'notice_period_start_date': str(employee.notice_period_start_date) if employee.notice_period_start_date else None,
        'is_active': employee.is_active,
    }


def handle_employee_request(message, producer):
    try:
        request_data = message.value
        correlation_id = request_data.get("correlation_id")
        employee_id = request_data.get("employee_id")
        action = request_data.get("action")
        
        print(f"Received employee request: {action} | Employee: {employee_id}")
        
        response = {
            "correlation_id": correlation_id,
            "status": "error",
            "error": "Invalid action"
        }
        
        if action == "get_employee_details":
            try:
                employee = Employee.objects.get(id=employee_id, is_active=True)
                
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "employee": serialize_employee(employee)
                }
                
                print(f"Found employee: {employee.full_name}")
                
            except Employee.DoesNotExist:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": f"Employee with ID {employee_id} not found"
                }
                print(f"Employee not found: {employee_id}")
            
            except Employee.MultipleObjectsReturned:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": "Multiple employees found with same ID"
                }
                print(f"Multiple employees found: {employee_id}")
        
        # Send response back
        producer.send('employee_data_responses', response)
        producer.flush()
        
        print(f"Sent employee response for correlation_id: {correlation_id}")
        
    except Exception as e:
        print(f"Error handling employee request: {e}")
        
        # Send error response
        error_response = {
            "correlation_id": request_data.get("correlation_id", "unknown"),
            "status": "error",
            "error": str(e)
        }
        producer.send('employee_data_responses', error_response)
        producer.flush()


def start_employee_request_consumer():
    print("Starting Employee Request Consumer...")
    
    # Get producer for responses
    producer = get_kafka_producer()
    
    if not producer:
        print("Failed to connect Kafka producer. Exiting.")
        return
    
    # Create consumer
    consumer = KafkaConsumer(
        'employee_data_requests',
        bootstrap_servers=KAFKA_BROKER,
        group_id='employee_service_consumer_group',
        auto_offset_reset='latest',
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    print("Employee consumer connected and listening for requests...")
    
    try:
        for message in consumer:
            handle_employee_request(message, producer)
    except KeyboardInterrupt:
        print("\nShutting down Employee consumer...")
    except Exception as e:
        print(f"Consumer error: {e}")
    finally:
        consumer.close()
        producer.close()
        print("Employee consumer shutdown complete")