import json
import uuid
import time
from kafka import KafkaProducer, KafkaConsumer
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})


class PolicyServiceClient:
    
    TIMEOUT_SECONDS = 10
    
    @staticmethod
    def get_active_policy(tenant_id, policy_type):

        correlation_id = str(uuid.uuid4())
        
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            
            request_payload = {
                "correlation_id": correlation_id,
                "tenant_id": str(tenant_id),
                "policy_type": policy_type,
                "action": "get_active_policy"
            }
            
            producer.send(KAFKA_TOPICS['POLICY_REQUEST'], request_payload)
            producer.flush()
            producer.close()
            
            print(f"Sent policy request: {request_payload}")
            
            consumer = KafkaConsumer(
                KAFKA_TOPICS['POLICY_RESPONSE'],
                bootstrap_servers=KAFKA_BROKER,
                group_id=f"leave_service_policy_{correlation_id}",
                auto_offset_reset='latest',
                value_deserializer=lambda v: json.loads(v),
                consumer_timeout_ms=PolicyServiceClient.TIMEOUT_SECONDS * 1000
            )
            
            start_time = time.time()
            
            for message in consumer:
                response = message.value
                
                if response.get("correlation_id") == correlation_id:
                    consumer.close()
                    
                    if response.get("status") == "success":
                        print(f"Received policy response: {response.get('policy', {}).get('policy_name')}")
                        return response.get("policy")
                    else:
                        print(f"Policy service error: {response.get('error')}")
                        return None
                
                if time.time() - start_time > PolicyServiceClient.TIMEOUT_SECONDS:
                    break
            
            consumer.close()
            print("Policy service timeout")
            return None
            
        except Exception as e:
            print(f"Error fetching policy via Kafka: {e}")
            return None