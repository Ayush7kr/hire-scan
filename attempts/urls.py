"""Test attempt URLs — includes candidate dashboard."""
from django.urls import path
from attempts.views import candidate_dashboard

urlpatterns = [
    path('dashboard/', candidate_dashboard, name='candidate_dashboard'),
    # Phase 3: test taking, submission, results
]
