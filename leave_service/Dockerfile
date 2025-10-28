# -----------------------
# Policy Service Dockerfile
# -----------------------
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/

# Set environment variables for Django
ENV DJANGO_SETTINGS_MODULE=leave_service.settings
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
