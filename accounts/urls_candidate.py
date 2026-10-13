"""Candidate authentication URLs."""
from django.urls import path
from accounts.views import candidate_login, candidate_send_otp, candidate_verify_otp, candidate_logout

urlpatterns = [
    path('login/', candidate_login, name='candidate_login'),
    path('send-otp/', candidate_send_otp, name='candidate_send_otp'),
    path('verify-otp/', candidate_verify_otp, name='candidate_verify_otp'),
    path('logout/', candidate_logout, name='candidate_logout'),
]
