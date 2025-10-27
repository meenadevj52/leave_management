import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    user_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    tenant_id = models.UUIDField(editable=False)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=50, blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email
