import json
import uuid
import time
from kafka import KafkaProducer, KafkaConsumer
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})


class EmployeeServiceClient:
    
    TIMEOUT_SECONDS = 10
    
    @staticmethod
    def get_employee_details(employee_id):

        correlation_id = str(uuid.uuid4())
        
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            
            request_payload = {
                "correlation_id": correlation_id,
                "employee_id": str(employee_id),
                "action": "get_employee_details"
            }
            
            producer.send(KAFKA_TOPICS['EMPLOYEE_REQUEST'], request_payload)
            producer.flush()
            producer.close()
            
            print(f"Sent employee request: {request_payload}")
            
            consumer = KafkaConsumer(
                KAFKA_TOPICS['EMPLOYEE_RESPONSE'],
                bootstrap_servers=KAFKA_BROKER,
                group_id=f"leave_service_employee_{correlation_id}",
                auto_offset_reset='latest',
                value_deserializer=lambda v: json.loads(v),
                consumer_timeout_ms=EmployeeServiceClient.TIMEOUT_SECONDS * 1000
            )
            
            start_time = time.time()
            
            for message in consumer:
                response = message.value
                
                if response.get("correlation_id") == correlation_id:
                    consumer.close()
                    
                    if response.get("status") == "success":
                        print(f"Received employee response: {response.get('employee', {}).get('full_name', 'Unknown')}")
                        return response.get("employee")
                    else:
                        print(f"Employee service error: {response.get('error')}")
                        return None
                
                if time.time() - start_time > EmployeeServiceClient.TIMEOUT_SECONDS:
                    break
            
            consumer.close()
            print("Employee service timeout")
            return None
            
        except Exception as e:
            print(f"Error fetching employee via Kafka: {e}")
            return None
    
    @staticmethod
    def get_manager_details(manager_id):
        return EmployeeServiceClient.get_employee_details(manager_id)