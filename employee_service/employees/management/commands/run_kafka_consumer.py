from django.core.management.base import BaseCommand
from employees.consumers import start_employee_request_consumer


class Command(BaseCommand):
    help = 'Start Kafka consumer to handle employee data requests from other microservices'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('Starting Employee Service Kafka Consumer'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.WARNING('Press Ctrl+C to stop'))
        self.stdout.write('')
        
        try:
            start_employee_request_consumer()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nStopping consumer...'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError: {e}'))