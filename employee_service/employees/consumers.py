import os
import django
import json
import time
import socket
import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "employee_service.settings")
django.setup()

from kafka import KafkaConsumer, KafkaProducer
from django.conf import settings
from employees.models import Employee

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})

REQUEST_TOPIC = KAFKA_TOPICS.get("EMPLOYEE_REQUEST", "employee_data_requests")
RESPONSE_TOPIC = KAFKA_TOPICS.get("EMPLOYEE_RESPONSE", "employee_data_responses")


def serialize_employee(employee):

    return {
        "id": str(employee.id),
        "full_name": employee.full_name,
        "email": employee.email,
        "role": employee.role,
        "designation": getattr(employee, 'designation', employee.role),
        "department": employee.department,
        "manager_id": str(employee.manager_id) if employee.manager_id else None,
        "employment_type": getattr(employee, 'employment_type', 'Permanent'),
        "joining_date": str(employee.joining_date) if hasattr(employee, 'joining_date') else None,
        "salary_per_day": float(getattr(employee, 'salary_per_day', 0)),
        "is_in_notice_period": getattr(employee, 'is_in_notice_period', False),
        "is_department_head": getattr(employee, 'is_department_head', False),
    }


def handle_employee_request(data, producer):

    correlation_id = data.get("correlation_id")
    action = data.get("action")
    
    logger.info(f"Received: {action} | Correlation: {correlation_id}")
    
    try:
        if action == "get_employee_details":
            employee_id = data.get("employee_id")
            
            try:
                employee = Employee.objects.get(id=employee_id, is_active=True)
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "employee": serialize_employee(employee)
                }
                logger.info(f"Found employee: {employee.full_name}")
            except Employee.DoesNotExist:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": f"Employee not found with ID: {employee_id}"
                }
                logger.warning(f"Employee not found: {employee_id}")
            
            producer.send(RESPONSE_TOPIC, response)
        
        elif action == "get_employee_by_email":
            email = data.get("email")
            
            try:
                employee = Employee.objects.get(email=email, is_active=True)
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "employee": serialize_employee(employee)
                }
                logger.info(f"Found employee by email: {employee.full_name} ({email})")
            except Employee.DoesNotExist:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": f"Employee not found with email: {email}"
                }
                logger.warning(f"Employee not found: {email}")
            
            producer.send(RESPONSE_TOPIC, response)
        
        elif action == "get_users_by_role":
            tenant_id = data.get("tenant_id")
            role = data.get("role")
            
            logger.info(f"Searching for users with role: {role} in tenant: {tenant_id}")
            
            users = Employee.objects.filter(
                tenant_id=tenant_id,
                role=role,
                is_active=True
            )
            
            users_list = [serialize_employee(user) for user in users]
            
            response = {
                "correlation_id": correlation_id,
                "status": "success",
                "users": users_list
            }
            
            logger.info(f"Found {len(users_list)} user(s) with role {role}")
            producer.send(RESPONSE_TOPIC, response)
        
        elif action == "get_department_head":
            tenant_id = data.get("tenant_id")
            department = data.get("department")
            
            logger.info(f"Searching for department head: {department} in tenant: {tenant_id}")
            
            dept_head = Employee.objects.filter(
                tenant_id=tenant_id,
                department=department,
                is_department_head=True,
                is_active=True
            ).first()
            
            if not dept_head:
                dept_head = Employee.objects.filter(
                    tenant_id=tenant_id,
                    department=department,
                    role__in=['MANAGER', 'DEPARTMENT_HEAD', 'HEAD', 'TECH_MANAGER', 'TECHNOLOGY_MANAGER'],
                    is_active=True
                ).first()
            
            if dept_head:
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "department_head": serialize_employee(dept_head)
                }
                logger.info(f"Found department head: {dept_head.full_name}")
            else:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": f"Department head not found for department: {department}"
                }
                logger.warning(f"Department head not found for: {department}")
            
            producer.send(RESPONSE_TOPIC, response)
        else:
            response = {
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Invalid action: {action}"
            }
            logger.error(f"Invalid action: {action}")
            producer.send(RESPONSE_TOPIC, response)
        
        logger.info(f"Sending response to: {RESPONSE_TOPIC}")
        producer.flush()
        logger.info(f"Response sent for: {correlation_id}")
        logger.info("-" * 60)
        
    except Exception as e:
        logger.error(f"Error handling request: {e}", exc_info=True)
        response = {
            "correlation_id": correlation_id,
            "status": "error",
            "error": str(e)
        }
        producer.send(RESPONSE_TOPIC, response)
        producer.flush()


def start_consumer():
    logger.info("Starting Employee Data Consumer...")
    logger.info(f"Kafka Broker: {KAFKA_BROKER}")
    logger.info(f"Listening on: {REQUEST_TOPIC}")
    logger.info(f"Responding to: {RESPONSE_TOPIC}")
    
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )
    
    consumer = KafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id="employee_data_consumer_group",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    
    logger.info("Consumer ready and listening...")
    logger.info("=" * 60)
    
    try:
        for msg in consumer:
            logger.info("Message received from Kafka")
            data = msg.value
            handle_employee_request(data, producer)
    
    except KeyboardInterrupt:
        logger.info("\nShutting down consumer...")
    except Exception as e:
        logger.error(f"Consumer error: {e}", exc_info=True)
    finally:
        consumer.close()
        producer.close()
        logger.info("Consumer shutdown complete")


if __name__ == "__main__":
    start_consumer()