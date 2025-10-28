import os, django, json, time, socket
from datetime import date
from kafka import KafkaConsumer
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "leave_service.leave_service.settings")
django.setup()

from leaves.services.validation_service import LeaveValidationService
from leaves.services.policy_service import PolicyServiceClient

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.environ.get("EMPLOYEE_ONBOARD_TOPIC", "employee_onboard")

DEFAULT_ENTITLEMENTS = {"Annual": 15, "Sick": 10, "Casual": 10}


def wait_for_kafka(host="kafka", port=9092, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    raise RuntimeError("Kafka broker not reachable")


def ensure_balance_for_employee(tenant_id, employee_id, leave_type, year, base_days):
    bal, created = LeaveValidationService.get_or_create_balance(
        tenant_id, employee_id, leave_type, year, total_allocated=base_days
    )
    if created:
        bal.available = bal.total_allocated
        bal.used = 0
        bal.pending = 0
        bal.save()
    else:
        if bal.total_allocated != base_days:
            bal.total_allocated = base_days
            bal.update_balance()
    return bal, created


def start_consumer():
    wait_for_kafka(host=KAFKA_BROKER.split(":")[0], port=int(KAFKA_BROKER.split(":")[1]))

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id="leave_employee_onboard_group",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    print(f"Listening for onboarding events on topic: {TOPIC} ...")

    for msg in consumer:
        try:
            data = msg.value
            employee_id = data.get("employee_id")
            tenant_id = data.get("tenant_id")
            defaults = data.get("default_entitlements", {}) or DEFAULT_ENTITLEMENTS

            if not employee_id or not tenant_id:
                print("Skipping event due to missing employee_id/tenant_id:", data)
                continue

            print(f"Processing onboarding for employee={employee_id}, tenant={tenant_id}")
            year = date.today().year

            for leave_type in ["Annual", "Sick", "Casual"]:
                try:
                    policy = PolicyServiceClient.get_active_policy(tenant_id, leave_type)
                    if policy:
                        base = policy.get("entitlement", {}).get("base_days")
                        base_days = int(base) if base else defaults.get(leave_type)
                    else:
                        base_days = defaults.get(leave_type)
                except Exception as e:
                    print(f"Policy lookup failed for {leave_type}: {e}")
                    base_days = defaults.get(leave_type)

                bal, created = ensure_balance_for_employee(
                    tenant_id, employee_id, leave_type, year, base_days
                )
                print(f"  -> {leave_type}: allocated={base_days} created={created}")

        except Exception as e:
            print("Error processing onboarding event:", e)


if __name__ == "__main__":
    start_consumer()
