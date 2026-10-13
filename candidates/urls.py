"""Candidate management URLs."""
from django.urls import path
from candidates.views import (
    candidate_list,
    candidate_detail,
    candidate_edit,
    candidate_toggle_active,
    candidate_import,
    candidate_template_download,
    candidate_import_error_csv,
)

urlpatterns = [
    path('', candidate_list, name='candidate_list'),
    path('import/', candidate_import, name='candidate_import'),
    path('import/template/', candidate_template_download, name='candidate_template_download'),
    path('import/errors/', candidate_import_error_csv, name='candidate_import_error_csv'),
    path('<uuid:candidate_id>/', candidate_detail, name='candidate_detail'),
    path('<uuid:candidate_id>/edit/', candidate_edit, name='candidate_edit'),
    path('<uuid:candidate_id>/toggle-active/', candidate_toggle_active, name='candidate_toggle_active'),
]
