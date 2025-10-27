from kafka import KafkaProducer, KafkaConsumer
import json
import uuid
import time

KAFKA_BROKER = "kafka:9092"

def get_producer():
    for _ in range(5):
        try:
            return KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        except Exception:
            print("Kafka not ready, retrying in 5 seconds...")
            time.sleep(5)
    raise Exception("Kafka broker not available after retries")


def send_tenant_verification_request(tenant_id):
    producer = get_producer()
    correlation_id = str(uuid.uuid4())
    message = {
        "tenant_id": tenant_id,
        "correlation_id": correlation_id,
        "type": "tenant_verification_request"
    }

    producer.send("tenant_requests", message)
    producer.flush()

    consumer = KafkaConsumer(
        "tenant_responses",
        bootstrap_servers=KAFKA_BROKER,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id=str(uuid.uuid4()),
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    timeout = time.time() + 5
    for msg in consumer:
        if msg.value.get("correlation_id") == correlation_id:
            consumer.close()
            return msg.value.get("tenant_exists", False)
        if time.time() > timeout:
            consumer.close()
            return False
