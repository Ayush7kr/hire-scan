"""Admin authentication URLs."""
from django.urls import path
from accounts.views import admin_login, admin_logout
from analytics.views import admin_dashboard

urlpatterns = [
    path('login/', admin_login, name='admin_login'),
    path('logout/', admin_logout, name='admin_logout'),
    path('dashboard/', admin_dashboard, name='admin_dashboard'),
]

