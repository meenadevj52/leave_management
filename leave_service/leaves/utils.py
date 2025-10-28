import uuid


def to_uuid(val):
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return None


def clean_leave_data(leave_app):
    data = {}
    for field in leave_app._meta.get_fields():
        if field.many_to_many:
            data[field.name] = list(getattr(leave_app, field.name).values_list('id', flat=True))
        elif field.one_to_many or (field.one_to_one and field.auto_created):
            continue
        else:
            value = getattr(leave_app, field.name, None)
            if isinstance(value, uuid.UUID):
                value = str(value)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            data[field.name] = value
    return data