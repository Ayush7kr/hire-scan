"""Candidate-to-Test Registration URLs."""
from django.urls import path
from assessments.views import (
    registration_list,
    registration_create,
    registration_bulk_summary,
    registration_detail,
    registration_cancel,
    notification_list,
    notification_retry,
)

urlpatterns = [
    path('', registration_list, name='registration_list'),
    path('create/', registration_create, name='registration_create'),
    path('summary/', registration_bulk_summary, name='registration_bulk_summary'),
    path('notifications/', notification_list, name='notification_list'),
    path('notifications/<uuid:log_id>/retry/', notification_retry, name='notification_retry'),
    path('<uuid:registration_id>/', registration_detail, name='registration_detail'),
    path('<uuid:registration_id>/cancel/', registration_cancel, name='registration_cancel'),
]

