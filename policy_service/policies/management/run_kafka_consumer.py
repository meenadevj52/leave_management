from django.core.management.base import BaseCommand
from policies.consumers import start_policy_request_consumer


class Command(BaseCommand):
    help = 'Start Kafka consumer to handle policy data requests from other microservices'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('Starting Policy Service Kafka Consumer'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.WARNING('Press Ctrl+C to stop'))
        self.stdout.write('')
        
        try:
            start_policy_request_consumer()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nStopping consumer...'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError: {e}'))