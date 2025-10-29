import uuid
import json
from decimal import Decimal
from datetime import date, datetime
from django.db import models


def to_uuid(val):

    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError, TypeError):
        return None


class JSONEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, models.Model):
            return str(obj.pk)
        elif hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


def serialize_value(value):

    if value is None:
        return None
    elif isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, uuid.UUID):
        return str(value)
    elif isinstance(value, models.Model):
        return str(value.pk) if hasattr(value, 'pk') else str(value)
    elif isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    elif isinstance(value, set):
        return [serialize_value(item) for item in value]
    else:
        return value


def clean_leave_data(leave_app):

    if not leave_app:
        return {}
    
    exclude_fields = {
        'approvals',
        'leave_comments',
        'audit_logs',
        '_state',
        '_prefetched_objects_cache',
    }
    
    data = {}
    
    for field in leave_app._meta.fields:
        field_name = field.name
        
        if field_name in exclude_fields:
            continue
        
        try:
            field_value = getattr(leave_app, field_name, None)
            data[field_name] = serialize_value(field_value)
        except Exception as e:
            data[field_name] = f"<Serialization Error: {str(e)}>"
    
    return data


def to_json(obj):

    return json.dumps(obj, cls=JSONEncoder)


def safe_decimal(value, default=0):
    
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, AttributeError):
        return Decimal(str(default))


def safe_float(value, default=0.0):
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return default