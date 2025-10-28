import uuid
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from rest_framework import authentication, exceptions
from django.conf import settings

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
AUTH_REQUEST_TOPIC = "validate_token_requests"


class AuthUser:
    def __init__(self, user_id, tenant_id, role):
        self.id = user_id
        self.tenant_id = tenant_id
        self.role = role
        self.is_authenticated = True


class AuthServiceTokenAuthentication(authentication.BaseAuthentication):
    TIMEOUT_SECONDS = 5

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None  # DRF will treat as anonymous

        token = auth_header.split(" ")[1]
        correlation_id = str(uuid.uuid4())
        reply_topic = f"validate_token_responses_{correlation_id}"

        # Send token validation request to Auth service via Kafka
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8")
        )
        producer.send(AUTH_REQUEST_TOPIC, {
            "token": token,
            "reply_topic": reply_topic,
            "correlation_id": correlation_id,
        })
        producer.flush()

        # Consume the response from Auth service
        consumer = KafkaConsumer(
            reply_topic,
            bootstrap_servers=KAFKA_BROKER,
            group_id=f"policy_service_{correlation_id}",
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v)
        )

        start_time = time.time()
        while True:
            for message in consumer:
                resp = message.value
                if resp.get("correlation_id") == correlation_id:
                    if resp.get("status") != "success":
                        raise exceptions.AuthenticationFailed(resp.get("message"))

                    # Return a user-like object for DRF
                    user_data = resp
                    user = AuthUser(
                        user_id=user_data["user_id"],
                        tenant_id=user_data["tenant_id"],
                        role=user_data["role"]
                    )
                    return (user, None)

            if time.time() - start_time > self.TIMEOUT_SECONDS:
                raise exceptions.AuthenticationFailed("Auth service timeout")
