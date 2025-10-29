import uuid
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from rest_framework import authentication, exceptions
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


def get_kafka_producer(retry_delay=2, max_retries=5):

    producer = None
    attempts = 0
    while not producer and attempts < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            attempts += 1
            print("Kafka producer not ready, retrying...", e)
            time.sleep(retry_delay)
    return producer


def get_kafka_consumer(topic, group_id, consumer_timeout_ms=5000):

    consumer = None
    attempts = 0
    while not consumer and attempts < 5:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=KAFKA_BROKER,
                group_id=group_id,
                auto_offset_reset="earliest",
                consumer_timeout_ms=consumer_timeout_ms,
                value_deserializer=lambda v: json.loads(v)
            )
        except Exception as e:
            attempts += 1
            print("Kafka not ready for consumer, retrying 5s...", e)
            time.sleep(5)
    return consumer


class AuthServiceTokenAuthentication(authentication.BaseAuthentication):

    TIMEOUT_SECONDS = 15

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]
        correlation_id = str(uuid.uuid4())
        reply_topic = f"validate_token_responses_{correlation_id}"

        producer = get_kafka_producer()
        if not producer:
            raise exceptions.AuthenticationFailed("Auth kafka producer not available")

        try:
            producer.send(
                "validate_token_requests",
                {"token": token, "reply_topic": reply_topic, "correlation_id": correlation_id},
            )
            producer.flush()
        except Exception:
            raise exceptions.AuthenticationFailed("Failed to send auth request")

        consumer = get_kafka_consumer(
            reply_topic,
            f"employee_service_{correlation_id}",
            consumer_timeout_ms=self.TIMEOUT_SECONDS * 1000
        )
        if not consumer:
            raise exceptions.AuthenticationFailed("Auth kafka consumer could not be created")

        start_time = time.time()
        try:
            for message in consumer:
                resp = message.value
                if resp.get("correlation_id") == correlation_id:
                    consumer.close()
                    try:
                        producer.close()
                    except Exception:
                        pass

                    if resp.get("status") != "success":
                        raise exceptions.AuthenticationFailed(resp.get("message", "Authentication failed"))

                    user_id = resp.get("user_id") or resp.get("user_uuid")
                    tenant_id = resp.get("tenant_id")
                    role = resp.get("role")
                    email = resp.get("email", "")

                    if not user_id or not tenant_id:
                        raise exceptions.AuthenticationFailed("Auth service response missing user_id/tenant_id")


                    class AuthUser:
                        def __init__(self, user_id, tenant_id, role, email):
                            self.id = user_id
                            self.tenant_id = tenant_id
                            self.role = role
                            self.email = email
                            self.is_authenticated = True

                        def __str__(self):
                            return f"<AuthUser {self.email} ({self.role})>"


                    user = AuthUser(user_id, tenant_id, role, email)
                    return (user, None)


            raise exceptions.AuthenticationFailed("Auth service timeout")

        finally:
            try:
                consumer.close()
            except Exception:
                pass
            try:
                producer.close()
            except Exception:
                pass
