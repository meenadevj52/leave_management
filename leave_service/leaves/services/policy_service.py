import json
import uuid
import time
import logging
from kafka import KafkaProducer, KafkaConsumer
from django.conf import settings

logger = logging.getLogger(__name__)

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})

POLICY_REQUEST_TOPIC = KAFKA_TOPICS.get("POLICY_REQUEST", "policy_data_requests")
POLICY_RESPONSE_TOPIC = KAFKA_TOPICS.get("POLICY_RESPONSE", "policy_data_responses")


class PolicyServiceClient:

    TIMEOUT_SECONDS = 10

    @staticmethod
    def get_active_policy(tenant_id, policy_type):
        correlation_id = str(uuid.uuid4())

        try:
            logger.info(f"📡 Creating consumer for policy response...")
            consumer = KafkaConsumer(
                POLICY_RESPONSE_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                group_id=f"leave_policy_client_{correlation_id}",
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v),
                consumer_timeout_ms=PolicyServiceClient.TIMEOUT_SECONDS * 1000,
            )

            logger.info(f"Sending policy request...")
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )

            request_payload = {
                "correlation_id": correlation_id,
                "tenant_id": str(tenant_id),
                "policy_type": policy_type,
                "action": "get_active_policy",
            }

            producer.send(POLICY_REQUEST_TOPIC, request_payload)
            producer.flush()
            producer.close()

            logger.info(f"Sent policy request to {POLICY_REQUEST_TOPIC}: {request_payload}")

            logger.info(f"Waiting for policy response...")
            start_time = time.time()
            for message in consumer:
                response = message.value
                logger.info(f"Received message: correlation_id={response.get('correlation_id')}")
                
                if response.get("correlation_id") == correlation_id:
                    consumer.close()
                    
                    if response.get("status") == "success":
                        policy = response.get("policy")
                        logger.info(f"Received policy: {policy.get('policy_name')} (v{policy.get('version')})")
                        return policy
                    else:
                        logger.warning(f"Policy service error: {response.get('error')}")
                        return None
                
                if time.time() - start_time > PolicyServiceClient.TIMEOUT_SECONDS:
                    logger.warning(f"Timeout reached after {PolicyServiceClient.TIMEOUT_SECONDS}s")
                    break

            consumer.close()
            logger.warning("Policy service timeout (no matching response)")
            return None

        except Exception as e:
            logger.error(f"Error fetching policy via Kafka: {e}", exc_info=True)
            try:
                consumer.close()
            except:
                pass
            return None