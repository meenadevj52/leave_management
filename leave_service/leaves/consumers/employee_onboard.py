import os
import django
import json
import time
import socket
import logging
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "leave_service.settings")
django.setup()

from kafka import KafkaConsumer
from django.conf import settings
from leaves.models import LeaveBalance
from leaves.services.policy_service import PolicyServiceClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPICS = getattr(settings, "KAFKA_TOPICS", {})
TOPIC = KAFKA_TOPICS.get("EMPLOYEE_ONBOARD", "employee_onboard")


def wait_for_kafka(host="kafka", port=9092, timeout=60):
    logger.info(f"Waiting for Kafka at {host}:{port}...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                logger.info(f"Kafka broker reachable at {host}:{port}")
                return True
        except OSError:
            time.sleep(2)
    
    raise RuntimeError(f"Kafka broker not reachable at {host}:{port}")


def create_or_update_leave_balance(tenant_id, employee_id, leave_type, year, total_allocated):
    balance, created = LeaveBalance.objects.get_or_create(
        tenant_id=tenant_id,
        employee_id=employee_id,
        leave_type=leave_type,
        year=year,
        defaults={
            'total_allocated': total_allocated,
            'available': total_allocated,
            'used': 0,
            'pending': 0,
            'carried_forward': 0,
            'encashed': 0
        }
    )
    
    if not created and balance.total_allocated != total_allocated:
        logger.info(f"Balance already exists with {balance.total_allocated} days, updating to {total_allocated}")
        balance.total_allocated = total_allocated
        balance.available = total_allocated
        balance.save()
    
    return balance, created


def process_employee_onboarding(employee_id, tenant_id, employment_type='Permanent'):
    logger.info(f"Processing onboarding: Employee={employee_id}, Tenant={tenant_id}")
    
    current_year = date.today().year
    leave_types = ['Annual', 'Sick', 'Casual']
    
    for leave_type in leave_types:
        try:
            policy = None
            total_allocated = 0
            
            try:
                policy = PolicyServiceClient.get_active_policy(tenant_id, leave_type)
                logger.info(f"Fetched policy for {leave_type}: {policy.get('policy_name') if policy else 'None'}")
            except Exception as exc:
                logger.warning(f"Could not fetch policy for {leave_type}: {exc}")
                policy = None
            
            if policy:
                entitlement = policy.get('entitlement', {})
                base_days = entitlement.get('base_days', 0)
                
                if employment_type == 'Probation' and leave_type in ['Annual', 'Casual']:
                    total_allocated = 0
                    logger.info(f"Probation restriction: {leave_type} set to 0")
                elif employment_type == 'Intern' and leave_type in ['Annual', 'Casual']:
                    total_allocated = 0
                    logger.info(f"Intern restriction: {leave_type} set to 0")
                else:
                    total_allocated = base_days
                    logger.info(f"Policy found: {leave_type} = {total_allocated} days")
            else:
                total_allocated = 0
                logger.info(f"No active policy for {leave_type}, creating with 0 days")
            
            balance, created = create_or_update_leave_balance(
                tenant_id=tenant_id,
                employee_id=employee_id,
                leave_type=leave_type,
                year=current_year,
                total_allocated=total_allocated
            )
            
            action = "Created" if created else "Updated"
            logger.info(f"{action} {leave_type} balance: {total_allocated} days (ID: {balance.id})")
            
        except Exception as exc:
            logger.error(f"Error processing {leave_type}: {exc}", exc_info=True)


def start_consumer():
    logger.info("Starting Employee Onboard Consumer...")
    
    host, port = KAFKA_BROKER.split(":")
    try:
        wait_for_kafka(host=host, port=int(port))
    except RuntimeError as e:
        logger.error(str(e))
        return

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id="leave_employee_onboard_group",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    
    logger.info(f"Consumer listening on topic: {TOPIC}")
    logger.info("=" * 60)
    
    try:
        for msg in consumer:
            try:
                data = msg.value
                employee_id = data.get("employee_id")
                tenant_id = data.get("tenant_id")
                employment_type = data.get("employment_type", "Permanent")
                
                if not employee_id or not tenant_id:
                    logger.warning(f"Skipping event - missing employee_id or tenant_id: {data}")
                    continue
                
                process_employee_onboarding(employee_id, tenant_id, employment_type)
                logger.info("=" * 60)
                
            except Exception as exc:
                logger.error(f"Error processing onboarding event: {exc}", exc_info=True)
    
    except KeyboardInterrupt:
        logger.info("\n Shutting down consumer...")
    except Exception as e:
        logger.error(f" Consumer error: {e}", exc_info=True)
    finally:
        consumer.close()
        logger.info(" Consumer shutdown complete")


if __name__ == "__main__":
    start_consumer()