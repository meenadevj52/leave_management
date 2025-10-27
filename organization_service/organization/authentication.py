import uuid
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from rest_framework import authentication, exceptions
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

def get_kafka_producer():
    producer = None
    while not producer:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print("Kafka not ready, retrying in 5s...", e)
            time.sleep(5)
    return producer


def get_kafka_consumer(topic, group_id):
    consumer = None
    while not consumer:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=KAFKA_BROKER,
                group_id=group_id,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v)
            )
        except Exception as e:
            print("Kafka not ready for consumer, retrying 5s...", e)
            time.sleep(5)
    return consumer


class AuthServiceTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1]
        correlation_id = str(uuid.uuid4())
        reply_topic = f"validate_token_responses_{correlation_id}"

        producer = get_kafka_producer()
        producer.send(
            "validate_token_requests",
            {"token": token, "reply_topic": reply_topic, "correlation_id": correlation_id},
        )
        producer.flush()

        consumer = get_kafka_consumer(reply_topic, f"employee_service_{correlation_id}")
        start_time = time.time()
        timeout = 15

        for message in consumer:
            resp = message.value
            if resp.get("correlation_id") == correlation_id:
                if resp.get("status") != "success":
                    raise exceptions.AuthenticationFailed(resp.get("message"))

                class AuthUser:
                    def __init__(self, data):
                        self.id = data["user_id"]
                        self.tenant_id = data["tenant_id"]
                        self.role = data["role"]
                        self.is_authenticated = True

                return AuthUser(resp), None

            if time.time() - start_time > timeout:
                raise exceptions.AuthenticationFailed("Auth service timeout")
