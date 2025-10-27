import os
import time
import socket
import json
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auth_service.settings")
import django
django.setup()

from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()

KAFKA_BROKER = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", settings.KAFKA_BOOTSTRAP_SERVERS)
REQUEST_TOPIC = "validate_token_requests"

def wait_for_kafka(host="kafka", port=9092, timeout=30):
    print(f"Waiting for Kafka at {host}:{port}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                print("Kafka is ready")
                return True
        except OSError:
            time.sleep(1)
    raise RuntimeError("Kafka broker not reachable")

wait_for_kafka(host=KAFKA_BROKER.split(":")[0], port=int(KAFKA_BROKER.split(":")[1]))

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

while True:
    try:
        consumer = KafkaConsumer(
            REQUEST_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id="auth_token_validation_group",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )
        print(f"Listening for Kafka events on topic: {REQUEST_TOPIC}...")
        break
    except NoBrokersAvailable:
        print("Kafka broker not available yet, retrying in 5 seconds...")
        time.sleep(5)

for message in consumer:
    data = message.value
    token = data.get("token")
    reply_topic = data.get("reply_topic")
    correlation_id = data.get("correlation_id")

    response = {"correlation_id": correlation_id}

    try:
        decoded_token = UntypedToken(token)
        user_id = decoded_token.payload.get("user_id")
        user = User.objects.get(id=user_id)

        response.update({
            "status": "success",
            "user_id": str(user.user_uuid),
            "tenant_id": str(user.tenant_id),
            "role": user.role,
            "email": user.email,
        })
    except (User.DoesNotExist, InvalidToken, TokenError):
        response.update({
            "status": "error",
            "message": "Invalid token or user not found"
        })

    producer.send(reply_topic, response)
    producer.flush()
    print(f"Sent token validation response to {reply_topic}")
