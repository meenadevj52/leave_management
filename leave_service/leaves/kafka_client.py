import json
import time
import uuid
from kafka import KafkaProducer, KafkaConsumer
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

def get_kafka_producer(retry_delay=2):
    producer = None
    while not producer:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print("Kafka producer not ready, retrying...", e)
            time.sleep(retry_delay)
    return producer

def wait_for_reply(reply_topic, correlation_id, timeout=5):
    consumer = KafkaConsumer(
        reply_topic,
        bootstrap_servers=KAFKA_BROKER,
        auto_offset_reset="earliest",
        consumer_timeout_ms=timeout * 1000,
        value_deserializer=lambda m: json.loads(m.decode("utf-8"))
    )
    try:
        for message in consumer:
            resp = message.value
            if resp.get("correlation_id") == correlation_id:
                return resp
    finally:
        consumer.close()
    raise TimeoutError("No response from remote service")
