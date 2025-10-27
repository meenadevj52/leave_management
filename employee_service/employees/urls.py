from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EmployeeViewSet, EmployeeDocumentViewSet,
    EmployeeCreateView, EmployeeUpdateView
)

router = DefaultRouter()
router.register(r'', EmployeeViewSet, basename='employee')
router.register(r'documents', EmployeeDocumentViewSet, basename='employee-document')

urlpatterns = [
    path('', include(router.urls)),
    
    path('create/', EmployeeCreateView.as_view(), name='create_employee'),
    path('update/<uuid:id>/', EmployeeUpdateView.as_view(), name='update_employee'),
]