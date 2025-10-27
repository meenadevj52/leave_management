import os
import django
import json
import time
import socket
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from django.contrib.auth import get_user_model
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auth_service.settings")
django.setup()

User = get_user_model()

KAFKA_BROKER = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", settings.KAFKA_BOOTSTRAP_SERVERS)
TOPIC = "employee_created"

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

while True:
    try:
        consumer = KafkaConsumer(
            TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            group_id="auth_employee_group",
            value_deserializer=lambda m: json.loads(m.decode("utf-8"))
        )
        print(f"🎧 Listening for Kafka events on topic: {TOPIC}...")
        break
    except NoBrokersAvailable:
        print("Kafka broker not available yet, retrying in 5 seconds...")
        time.sleep(5)

for message in consumer:
    print("Received a message from Kafka!")
    print(f"Raw message: {message.value}")

    data = message.value
    email = data.get("email")
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    tenant_id = data.get("tenant_id")
    role = data.get("role")
    default_password = data.get("default_password")

    print(f"Processing employee: {email}, tenant_id: {tenant_id}, role: {role}")

    username = email.split("@")[0]

    if not User.objects.filter(email=email).exists():
        User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            tenant_id=tenant_id,
            role=role,
            password=default_password
        )
        print(f"Created Auth user for employee {email}")
    else:
        print(f"User {email} already exists")
