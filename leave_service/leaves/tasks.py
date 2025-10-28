import json
import time
from kafka import KafkaProducer
from django.conf import settings


def get_kafka_producer():
    producer = None
    retry_count = 0
    max_retries = 3
    
    while not producer and retry_count < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print(f"Kafka not ready, retrying in 5s... ({retry_count}/{max_retries})", e)
            time.sleep(5)
            retry_count += 1
    
    return producer


def send_leave_event(event_name, payload):
    try:
        producer = get_kafka_producer()
        if not producer:
            print(f"Kafka producer not available, skipping event: {event_name}")
            return
        
        producer.send(event_name, payload)
        producer.flush()
        print(f"Kafka event sent: {event_name} → {payload}")
    except Exception as e:
        print(f"Kafka error on {event_name}: {e}")