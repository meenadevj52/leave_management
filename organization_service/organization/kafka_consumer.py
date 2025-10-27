import sys, os, django, time, socket, json
from kafka import KafkaConsumer, KafkaProducer

sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "organization_service.settings")
django.setup()

from organization.models import Organization

def wait_for_kafka(host="kafka", port=9092, timeout=30):
    print(f"⏳ Waiting for Kafka at {host}:{port}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                print("Kafka is ready")
                return True
        except OSError:
            time.sleep(1)
    raise RuntimeError("Kafka broker not reachable")

wait_for_kafka()

KAFKA_BROKER = "kafka:9092"

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)

consumer = KafkaConsumer(
    "tenant_requests",
    bootstrap_servers=KAFKA_BROKER,
    auto_offset_reset="earliest",
    enable_auto_commit=True,
    group_id="organization_service_group",
    value_deserializer=lambda m: json.loads(m.decode("utf-8")),
)

print("Tenant verification consumer started...")

for message in consumer:
    data = message.value
    tenant_id = data.get("tenant_id")
    correlation_id = data.get("correlation_id")

    exists = Organization.objects.filter(id=tenant_id).exists()

    response = {
        "correlation_id": correlation_id,
        "tenant_exists": exists
    }

    producer.send("tenant_responses", response)
    producer.flush()

    print(f"Processed tenant_id={tenant_id}, exists={exists}")
