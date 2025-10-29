import uuid
from django.core.management.base import BaseCommand
from accounts.models import User

class Command(BaseCommand):
    help = "Creates a default admin user if not already present."

    def handle(self, *args, **options):
        admin_email = "admin@example.com"
        default_password = "admin123"
        default_tenant_id = uuid.uuid4()

        if User.objects.filter(email=admin_email).exists():
            self.stdout.write(self.style.WARNING(
                f"Admin user already exists: {admin_email}"
            ))
            return


        user = User.objects.create_user(
            username="admin",
            email=admin_email,
            password=default_password,
            tenant_id=default_tenant_id,
            role="Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.stdout.write(self.style.SUCCESS(
            f"Admin user created: {admin_email} / {default_password}"
        ))
