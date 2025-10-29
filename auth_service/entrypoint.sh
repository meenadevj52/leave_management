#!/bin/sh
set -e

cd /app

echo "Making migrations for accounts..."
python manage.py makemigrations accounts || echo "No changes to migrate for accounts."

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating default admin user if missing..."
python manage.py create_admin_user || echo "Failed to run create_admin_user command."

echo "Starting command: $@"
exec "$@"