import uuid
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from rest_framework.exceptions import PermissionDenied
from django.conf import settings


def get_kafka_producer():

    producer = None
    retry_count = 0
    max_retries = 3

    while not producer and retry_count < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        except Exception as e:
            print(f"Kafka not ready, retrying in 5s... ({retry_count}/{max_retries})", e)
            time.sleep(5)
            retry_count += 1

    return producer


def validate_tenant_via_kafka(tenant_id, timeout=10):

    correlation_id = str(uuid.uuid4())
    producer = get_kafka_producer()
    if not producer:
        raise PermissionDenied("Kafka producer unavailable for tenant validation.")


    request_event = {
        "tenant_id": str(tenant_id),
        "correlation_id": correlation_id,
    }

    producer.send("tenant_requests", request_event)
    producer.flush()
    print(f"Sent tenant validation request for {tenant_id}")

    consumer = KafkaConsumer(
        "tenant_responses",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id=f"employee_service_tenant_validator_{correlation_id}",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    tenant_valid = False
    start = time.time()

    for message in consumer:
        data = message.value
        if data.get("correlation_id") == correlation_id:
            tenant_valid = data.get("tenant_exists", False)
            break
        if time.time() - start > timeout:
            print("Tenant validation timed out")
            break

    consumer.close()
    producer.close()
    return tenant_valid
