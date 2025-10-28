import json
import time
from kafka import KafkaProducer
from django.conf import settings
from .models import Policy


def get_kafka_producer():
    producer = None
    while not producer:
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print("Kafka not ready, retrying in 5s...", e)
            time.sleep(5)
    return producer


def send_policy_event(event_name, policy_id):
    try:
        policy = Policy.objects.get(id=policy_id)
        payload = {
            "policy_id": str(policy.id),
            "tenant_id": str(policy.tenant_id),
            "policy_name": policy.policy_name,
            "status": policy.status,
            "version": policy.version
        }

        producer = get_kafka_producer()
        producer.send(event_name, payload)
        producer.flush()
        print(f"Kafka event sent: {event_name} → {payload}")

    except Exception as e:
        print(f"Kafka error on {event_name}: {e}")
