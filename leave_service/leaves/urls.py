from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LeaveApplicationViewSet, LeaveBalanceViewSet,
    LeaveCommentViewSet, HolidayViewSet
)

router = DefaultRouter()
router.register(r'applications', LeaveApplicationViewSet, basename='leave-application')
router.register(r'balances', LeaveBalanceViewSet, basename='leave-balance')
router.register(r'comments', LeaveCommentViewSet, basename='leave-comment')
router.register(r'holidays', HolidayViewSet, basename='holiday')

urlpatterns = [
    path('', include(router.urls)),
]