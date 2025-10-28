import json
import time
from kafka import KafkaConsumer, KafkaProducer
from django.conf import settings
from .models import Policy

KAFKA_BROKER = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


def get_kafka_producer():
    producer = None
    retry_count = 0
    max_retries = 5
    
    while not producer and retry_count < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            print("Kafka producer connected")
        except Exception as e:
            print(f"Kafka not ready, retrying... ({retry_count}/{max_retries}): {e}")
            time.sleep(5)
            retry_count += 1
    
    return producer


def serialize_policy(policy):
    return {
        'id': str(policy.id),
        'tenant_id': str(policy.tenant_id),
        'policy_name': policy.policy_name,
        'policy_type': policy.policy_type,
        'version': policy.version,
        'major_version': policy.major_version,
        'minor_version': policy.minor_version,
        'description': policy.description,
        'location': policy.location,
        'applies_to': policy.applies_to,
        'excludes': policy.excludes,
        'entitlement': policy.entitlement,
        'carry_forward': policy.carry_forward,
        'carry_forward_priority': policy.carry_forward_priority,
        'encashment': policy.encashment,
        'encashment_priority': policy.encashment_priority,
        'calculation_base': policy.calculation_base,
        'multiplier': float(policy.multiplier),
        'notice_period': policy.notice_period,
        'limit_per_month': policy.limit_per_month,
        'reset_leave_counter': policy.reset_leave_counter,
        'employment_duration': policy.employment_duration,
        'employment_duration_custom_days': policy.employment_duration_custom_days,
        'can_apply_previous_date': policy.can_apply_previous_date,
        'document_required': policy.document_required,
        'allow_multiple_day': policy.allow_multiple_day,
        'allow_half_day': policy.allow_half_day,
        'allow_comment': policy.allow_comment,
        'request_on_notice_period': policy.request_on_notice_period,
        'approval_route': policy.approval_route,
        'conditions': policy.conditions,
        'current_approval_step': policy.current_approval_step,
        'status': policy.status,
        'is_active': policy.is_active,
        'created_at': policy.created_at.isoformat() if policy.created_at else None,
        'updated_at': policy.updated_at.isoformat() if policy.updated_at else None,
    }


def handle_policy_request(message, producer):
    try:
        request_data = message.value
        correlation_id = request_data.get("correlation_id")
        tenant_id = request_data.get("tenant_id")
        policy_type = request_data.get("policy_type")
        action = request_data.get("action")
        
        print(f"Received policy request: {action} | Tenant: {tenant_id} | Type: {policy_type}")
        
        response = {
            "correlation_id": correlation_id,
            "status": "error",
            "error": "Invalid action"
        }
        
        if action == "get_active_policy":
            try:
                policy = Policy.objects.get(
                    tenant_id=tenant_id,
                    policy_type=policy_type,
                    status='ACTIVE',
                    is_active=True
                )
                
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "policy": serialize_policy(policy)
                }
                
                print(f"Found active policy: {policy.policy_name} ({policy.version})")
                
            except Policy.DoesNotExist:
                response = {
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": f"No active policy found for {policy_type} leave type"
                }
                print(f"No active policy found for {policy_type}")
                
            except Policy.MultipleObjectsReturned:
                policy = Policy.objects.filter(
                    tenant_id=tenant_id,
                    policy_type=policy_type,
                    status='ACTIVE',
                    is_active=True
                ).order_by('-major_version', '-minor_version').first()
                
                response = {
                    "correlation_id": correlation_id,
                    "status": "success",
                    "policy": serialize_policy(policy)
                }
                
                print(f"Found multiple active policies, returning latest: {policy.version}")
        
        elif action == "validate_leave_request":
            pass

        producer.send('policy_data_responses', response)
        producer.flush()
        
        print(f"Sent policy response for correlation_id: {correlation_id}")
        
    except Exception as e:
        print(f"Error handling policy request: {e}")
        
        error_response = {
            "correlation_id": request_data.get("correlation_id", "unknown"),
            "status": "error",
            "error": str(e)
        }
        producer.send('policy_data_responses', error_response)
        producer.flush()


def start_policy_request_consumer():
    print("Starting Policy Request Consumer...")
    
    producer = get_kafka_producer()
    
    if not producer:
        print("Failed to connect Kafka producer. Exiting.")
        return
    
    consumer = KafkaConsumer(
        'policy_data_requests',
        bootstrap_servers=KAFKA_BROKER,
        group_id='policy_service_consumer_group',
        auto_offset_reset='latest',
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    print("Policy consumer connected and listening for requests...")
    
    try:
        for message in consumer:
            handle_policy_request(message, producer)
    except KeyboardInterrupt:
        print("\n Shutting down Policy consumer...")
    except Exception as e:
        print(f"Consumer error: {e}")
    finally:
        consumer.close()
        producer.close()
        print("Policy consumer shutdown complete")


def start_policy_event_publisher():
    pass