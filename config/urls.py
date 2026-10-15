"""
URL configuration for HireScan project.
"""
from django.urls import path, include
from config.views import health_check

urlpatterns = [
    # Health checks for container orchestration and monitoring
    path('health/', health_check, name='health_check'),
    path('healthz/', health_check, name='healthz_check'),

    # Public homepage
    path('', include('accounts.urls_public')),

    # Administrator Portal & Authentication
    path('admin/', include('accounts.urls_admin')),
    path('admin/candidates/', include('candidates.urls')),
    path('admin/tests/', include('assessments.urls')),
    path('admin/registrations/', include('assessments.urls_registrations')),
    path('admin/analytics/', include('analytics.urls')),

    # Candidate Portal & Authentication
    path('candidate/', include('accounts.urls_candidate')),
    path('test/', include('attempts.urls')),

    # Backward / convenience alias for dashboard
    path('dashboard/', include('analytics.urls')),
]

