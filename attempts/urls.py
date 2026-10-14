"""Test attempt and candidate assessment URLs."""
from django.urls import path
from attempts import views

urlpatterns = [
    path('dashboard/', views.candidate_dashboard, name='candidate_dashboard'),
    path('instructions/<uuid:registration_id>/', views.test_instructions, name='test_instructions'),
    path('start/<uuid:registration_id>/', views.test_start, name='test_start'),
    path('take/<uuid:attempt_id>/', views.test_take, name='test_take'),
    path('autosave/<uuid:attempt_id>/', views.test_autosave, name='test_autosave'),
    path('submit/<uuid:attempt_id>/', views.test_submit, name='test_submit'),
    path('results/<uuid:attempt_id>/', views.test_results, name='test_results'),
    path('results/<uuid:attempt_id>/pdf/', views.attempt_scorecard_pdf, name='attempt_scorecard_pdf'),
]

