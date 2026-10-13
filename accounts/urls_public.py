"""Public-facing URLs (homepage)."""
from django.urls import path
from accounts.views import homepage

urlpatterns = [
    path('', homepage, name='homepage'),
]
