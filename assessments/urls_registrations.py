"""Candidate-to-Test Registration URLs."""
from django.urls import path
from assessments.views import (
    registration_list,
    registration_create,
    registration_bulk_summary,
    registration_detail,
    registration_cancel,
)

urlpatterns = [
    path('', registration_list, name='registration_list'),
    path('create/', registration_create, name='registration_create'),
    path('summary/', registration_bulk_summary, name='registration_bulk_summary'),
    path('<uuid:registration_id>/', registration_detail, name='registration_detail'),
    path('<uuid:registration_id>/cancel/', registration_cancel, name='registration_cancel'),
]

