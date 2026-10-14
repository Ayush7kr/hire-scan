"""
Analytics and Reporting URL Configurations.
"""
from django.urls import path
from analytics import views

urlpatterns = [
    # Main Executive Dashboard
    path('', views.admin_dashboard, name='admin_dashboard'),

    # Analytical Reports
    path('tests/', views.test_summary_report, name='analytics_test_summary'),
    path('tests/<uuid:test_id>/', views.test_summary_report, name='analytics_test_detail'),
    path('candidates/', views.candidate_performance_report, name='analytics_candidate_performance'),
    path('questions/', views.question_analysis_report, name='analytics_question_analysis'),
    path('topics/', views.topic_performance_report, name='analytics_topic_performance'),
    path('completion/', views.test_completion_report, name='analytics_completion_report'),

    # Batch CSV Exports
    path('export/tests/', views.export_test_summary_csv, name='analytics_export_tests'),
    path('export/tests/<uuid:test_id>/', views.export_test_summary_csv, name='analytics_export_test_detail'),
    path('export/candidates/', views.export_candidates_csv, name='analytics_export_candidates'),
    path('export/questions/', views.export_questions_csv, name='analytics_export_questions'),
    path('export/topics/', views.export_topics_csv, name='analytics_export_topics'),
    path('export/completion/', views.export_completion_csv, name='analytics_export_completion'),
]
