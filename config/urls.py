"""
URL configuration for HireScan project.
"""
from django.urls import path, include

urlpatterns = [
    # Public homepage
    path('', include('accounts.urls_public')),
    # Authentication
    path('admin/', include('accounts.urls_admin')),
    path('candidate/', include('accounts.urls_candidate')),
    # Admin portal
    path('dashboard/', include('analytics.urls')),
    # Candidate management
    path('dashboard/candidates/', include('candidates.urls')),
    # Assessment management
    path('dashboard/assessments/', include('assessments.urls')),
    # Test attempts
    path('test/', include('attempts.urls')),
]
