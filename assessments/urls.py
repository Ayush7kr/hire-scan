"""Assessment and Question Bank URLs."""
from django.urls import path
from assessments.views import (
    test_list,
    test_create,
    test_detail,
    test_edit,
    test_toggle_status,
    test_toggle_cancel,
    question_list,
    question_create,
    question_edit,
    question_delete,
    question_import,
    question_template_download,
    question_import_error_csv,
    admin_test_attempts,
    admin_attempt_detail,
)

urlpatterns = [
    path('', test_list, name='test_list'),
    path('create/', test_create, name='test_create'),
    path('questions/template/', question_template_download, name='question_template_download'),
    path('questions/errors/', question_import_error_csv, name='question_import_error_csv'),
    path('<uuid:test_id>/', test_detail, name='test_detail'),
    path('<uuid:test_id>/edit/', test_edit, name='test_edit'),
    path('<uuid:test_id>/toggle-status/', test_toggle_status, name='test_toggle_status'),
    path('<uuid:test_id>/toggle-cancel/', test_toggle_cancel, name='test_toggle_cancel'),
    path('<uuid:test_id>/questions/', question_list, name='question_list'),
    path('<uuid:test_id>/questions/create/', question_create, name='question_create'),
    path('<uuid:test_id>/questions/import/', question_import, name='question_import'),
    path('<uuid:test_id>/questions/<uuid:question_id>/edit/', question_edit, name='question_edit'),
    path('<uuid:test_id>/questions/<uuid:question_id>/delete/', question_delete, name='question_delete'),
    path('<uuid:test_id>/attempts/', admin_test_attempts, name='admin_test_attempts'),
    path('attempts/<uuid:attempt_id>/', admin_attempt_detail, name='admin_attempt_detail'),
]

