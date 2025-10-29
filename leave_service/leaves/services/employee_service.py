import json
import uuid
import time
import logging
from kafka import KafkaProducer, KafkaConsumer
from django.conf import settings

logger = logging.getLogger(__name__)

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})

EMPLOYEE_REQUEST_TOPIC = KAFKA_TOPICS.get("EMPLOYEE_REQUEST", "employee_data_requests")
EMPLOYEE_RESPONSE_TOPIC = KAFKA_TOPICS.get("EMPLOYEE_RESPONSE", "employee_data_responses")


class EmployeeServiceClient:

    TIMEOUT_SECONDS = 10

    @staticmethod
    def _send_kafka_request(action: str, payload: dict) -> dict:
        correlation_id = str(uuid.uuid4())
        
        try:
            consumer = KafkaConsumer(
                EMPLOYEE_RESPONSE_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                group_id=f"leave_employee_client_{correlation_id}",
                auto_offset_reset='earliest',
                value_deserializer=lambda v: json.loads(v),
                consumer_timeout_ms=EmployeeServiceClient.TIMEOUT_SECONDS * 1000
            )

            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )

            request_payload = {
                "correlation_id": correlation_id,
                "action": action,
                **payload
            }

            producer.send(EMPLOYEE_REQUEST_TOPIC, request_payload)
            producer.flush()
            producer.close()

            logger.info(f"Sent employee request: {action}")

            start_time = time.time()
            for message in consumer:
                response = message.value
                if response.get("correlation_id") == correlation_id:
                    consumer.close()
                    
                    if response.get("status") == "success":
                        logger.info(f"Received response for {action}")
                        return response
                    else:
                        logger.warning(f"Error in response: {response.get('error')}")
                        return None
                
                if time.time() - start_time > EmployeeServiceClient.TIMEOUT_SECONDS:
                    break

            consumer.close()
            logger.warning(f"Employee service timeout for {action}")
            return None

        except Exception as e:
            logger.error(f"Error in Kafka request for {action}: {e}", exc_info=True)
            try:
                consumer.close()
            except:
                pass
            return None

    @staticmethod
    def get_employee_details(employee_id):
        response = EmployeeServiceClient._send_kafka_request(
            action="get_employee_details",
            payload={"employee_id": str(employee_id)}
        )
        
        if response:
            return response.get("employee")
        return None

    @staticmethod
    def get_employee_by_email(email):
        response = EmployeeServiceClient._send_kafka_request(
            action="get_employee_by_email",
            payload={"email": email}
        )
        
        if response:
            employee = response.get("employee")
            if employee:
                logger.info(f"Found employee: {employee.get('full_name')} ({email})")
            return employee
        return None

    @staticmethod
    def get_manager_details(manager_id):
        return EmployeeServiceClient.get_employee_details(manager_id)

    @staticmethod
    def get_users_by_role(tenant_id, role):
        response = EmployeeServiceClient._send_kafka_request(
            action="get_users_by_role",
            payload={
                "tenant_id": str(tenant_id),
                "role": role
            }
        )
        
        if response:
            users = response.get("users", [])
            logger.info(f"Found {len(users)} users with role {role}")
            return users
        
        return []

    @staticmethod
    def get_department_head(tenant_id, department):
        response = EmployeeServiceClient._send_kafka_request(
            action="get_department_head",
            payload={
                "tenant_id": str(tenant_id),
                "department": department
            }
        )
        
        if response:
            dept_head = response.get("department_head")
            if dept_head:
                logger.info(f"Found department head for {department}: {dept_head.get('full_name')}")
            return dept_head
        
        return None