"""
URL configuration for HireScan project.
"""
from django.urls import path, include

urlpatterns = [
    # Public homepage
    path('', include('accounts.urls_public')),

    # Administrator Portal & Authentication
    path('admin/', include('accounts.urls_admin')),
    path('admin/candidates/', include('candidates.urls')),
    path('admin/tests/', include('assessments.urls')),
    path('admin/registrations/', include('assessments.urls_registrations')),

    # Candidate Portal & Authentication
    path('candidate/', include('accounts.urls_candidate')),
    path('test/', include('attempts.urls')),

    # Backward / convenience alias for dashboard
    path('dashboard/', include('analytics.urls')),
]
