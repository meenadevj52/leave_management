###HRMS - Leave Management System
A comprehensive Human Resource Management System (HRMS) built with Django using a Microservices Architecture.
It provides seamless employee onboarding, leave policy management, and multi-tenant support with hierarchical approval workflows.

###Prerequisites
Ensure the following are installed:

• Python 3.9+
• Docker
• Docker Compose
• Git
• Postman (optional, for API testing)

###Installation & Setup

Step 1: Clone the Repository
git clone https://github.com/meenadevj52/leave_management.git
cd leave-management

Step 2: Project Structure

leave-management/
├── auth_service/
│   ├── auth_app/
│   ├── manage.py
│   ├── requirements.txt
│   └── Dockerfile
├── employee_service/
│   ├── employees/
│   ├── consumers/
│   │   ├── employee_data_consumer.py
│   │   └── __init__.py
│   ├── manage.py
│   ├── requirements.txt
│   └── Dockerfile
├── policy_service/
│   ├── policies/
│   ├── consumers/
│   │   ├── policy_data_consumer.py
│   │   └── __init__.py
│   ├── manage.py
│   ├── requirements.txt
│   └── Dockerfile
├── leave_service/
│   ├── leaves/
│   │   ├── services/
│   │   │   ├── employee_service.py
│   │   │   ├── policy_service.py
│   │   │   ├── validation_service.py
│   │   │   └── approval_service.py
│   │   ├── consumers/
│   │   │   ├── employee_onboard.py
│   │   │   └── __init__.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   └── permissions.py
│   ├── manage.py
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml
├── README.md
└── postman/
    └── API_Collection.postman_collection.json

Step 1: Build and Start All Services
docker-compose build

##Before running compose up run this on your host machine
chmod +x auth_service/entrypoint.sh

##Then run
docker-compose up -d

Step 2: Verify Running Containers
docker ps

You should see containers for:
- auth_service
- employee_service
- policy_service
- leave_service
- kafka
- zookeeper
Default Admin Credentials
For initial setup, a default admin user is automatically created.

Use the following credentials to log in:

• Email: admin@example.com
• Password: admin123


###Testing APIs

Import the Postman collection file located at:
postman/API_Collection.postman_collection.json


###At last please go through the document attach at root directory