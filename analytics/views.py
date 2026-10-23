"""
Analytics and Reporting Views for HireScan.

Implements:
1. Executive Analytics Dashboard with responsive Chart.js visualisations.
2. Test Summary Reports (all tests & single test deep dive).
3. Candidate Performance Reports with ranks and percentiles.
4. Question Analysis Reports with assigned-attempt accuracy denominators.
5. Topic-Wise Performance & Improvement Reports.
6. Test Completion & Attempt-Pattern Reports.
7. Batch CSV Exports with Spreadsheet Formula Injection Protection.
"""
import csv
import json
import io
import re
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import admin_required
from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration
from attempts.models import TestAttempt, AttemptQuestion
from analytics.services import (
    sanitize_csv_cell,
    calculate_candidate_rankings_and_percentiles,
    get_dashboard_analytics,
    get_test_summary_analytics,
    get_question_analysis_analytics,
    get_topic_analytics,
    get_completion_analytics,
    parse_date_filter,
)


@admin_required
def admin_dashboard(request):
    """
    Administrator Analytics Dashboard.
    Visualises executive KPIs, responsive Chart.js visualisations, live filters,
    and recent activity stream.
    """
    filters = {
        'test_id': request.GET.get('test_id', '').strip(),
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to': request.GET.get('date_to', '').strip(),
        'status': request.GET.get('status', '').strip(),
    }

    analytics = get_dashboard_analytics(filters)
    all_tests = Test.objects.all().order_by('test_name')

    # Insufficient question bank count (for quick administrator alert)
    insufficient_tests_count = 0
    for t in all_tests:
        if Question.objects.filter(test=t).count() < t.total_questions:
            insufficient_tests_count += 1

    # Recent activity log
    recent_activity = ActivityLog.objects.select_related(
        'admin', 'candidate', 'attempt'
    ).order_by('-occurred_at')[:30]

    # Test pipeline summary table
    test_summaries = get_test_summary_analytics()[:6]

    context = {
        'admin_user': request.admin_user,
        'filters': filters,
        'all_tests': all_tests,
        'analytics': analytics,
        'insufficient_tests_count': insufficient_tests_count,
        'recent_activity': recent_activity,
        'test_summaries': test_summaries,
        # JSON-serialized data for Chart.js
        'chart_daily_labels': json.dumps(analytics['daily_labels']),
        'chart_daily_started': json.dumps(analytics['daily_started']),
        'chart_daily_completed': json.dumps(analytics['daily_completed']),
        'chart_pass_fail': json.dumps(analytics['pass_fail_chart']),
        'chart_test_labels': json.dumps(analytics['test_score_labels']),
        'chart_test_scores': json.dumps(analytics['test_score_data']),
        'chart_bucket_labels': json.dumps(analytics['bucket_labels']),
        'chart_bucket_counts': json.dumps(analytics['bucket_counts']),
        'chart_topic_labels': json.dumps(analytics['topic_labels']),
        'chart_topic_scores': json.dumps(analytics['topic_accuracies']),
        'chart_pipeline_labels': json.dumps(analytics['pipeline_labels']),
        'chart_pipeline_counts': json.dumps(analytics['pipeline_counts']),
    }
    return render(request, 'admin_portal/analytics/dashboard.html', context)


@admin_required
def test_summary_report(request, test_id=None):
    """
    Test Summary Report.
    If test_id is provided: renders in-depth report for that specific assessment,
    including candidate rankings, question accuracy, and topic breakdown.
    If test_id is None: lists all tests with comparative aggregate KPIs.
    """
    filters = {
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to': request.GET.get('date_to', '').strip(),
    }

    if test_id:
        test = get_object_or_404(Test, test_id=test_id)
        summary = get_test_summary_analytics(test_id=test_id, filters=filters)
        question_data = get_question_analysis_analytics(test_id=test_id)
        topic_data = get_topic_analytics(test_id=test_id)
        rankings = calculate_candidate_rankings_and_percentiles(test_id=test_id)

        # Retrieve candidate attempts for ranking table
        attempts_qs = TestAttempt.objects.filter(
            registration__test=test,
            status__in=['completed', 'expired']
        ).select_related('registration__candidate').order_by(
            '-score', 'time_taken_seconds', 'start_time'
        )

        attempts_with_ranks = []
        for att in attempts_qs:
            r_info = rankings.get(str(att.attempt_id), {})
            attempts_with_ranks.append({
                'attempt': att,
                'rank': r_info.get('rank', '—'),
                'percentile': r_info.get('percentile', '—'),
            })

        context = {
            'test': test,
            'summary': summary,
            'question_data': question_data,
            'topic_data': topic_data,
            'attempts_with_ranks': attempts_with_ranks,
            'filters': filters,
        }
        return render(request, 'admin_portal/analytics/test_summary_detail.html', context)

    # All tests overview
    all_tests = Test.objects.all().order_by('test_name')
    summaries = get_test_summary_analytics(filters=filters)

    context = {
        'summaries': summaries,
        'all_tests': all_tests,
        'filters': filters,
    }
    return render(request, 'admin_portal/analytics/test_summary_list.html', context)


@admin_required
def candidate_performance_report(request):
    """
    Candidate Performance Report.
    Lists candidate attempts with scores, percentages, ranks, percentiles,
    and time taken. Supports filtering by test, candidate search, status, and outcome.
    """
    test_id = request.GET.get('test_id', '').strip()
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    outcome_filter = request.GET.get('outcome', '').strip()
    date_from = parse_date_filter(request.GET.get('date_from', '').strip())
    date_to = parse_date_filter(request.GET.get('date_to', '').strip())

    attempts_qs = TestAttempt.objects.select_related(
        'registration__test', 'registration__candidate'
    ).order_by('-start_time')

    if test_id:
        attempts_qs = attempts_qs.filter(registration__test_id=test_id)

    if search_query:
        attempts_qs = attempts_qs.filter(
            Q(registration__candidate__name__icontains=search_query) |
            Q(registration__candidate__email__icontains=search_query)
        )

    if status_filter:
        attempts_qs = attempts_qs.filter(status=status_filter)

    if outcome_filter == 'passed':
        attempts_qs = attempts_qs.filter(is_passed=True)
    elif outcome_filter == 'failed':
        attempts_qs = attempts_qs.filter(is_passed=False)

    if date_from:
        attempts_qs = attempts_qs.filter(start_time__date__gte=date_from)
    if date_to:
        attempts_qs = attempts_qs.filter(start_time__date__lte=date_to)

    all_tests = Test.objects.all().order_by('test_name')

    # Precalculate rankings per test for accurate percentile lookup
    test_rankings_cache = {}
    if test_id:
        test_rankings_cache[test_id] = calculate_candidate_rankings_and_percentiles(test_id)

    paginator = Paginator(attempts_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Attach rankings to each item in current page
    for att in page_obj:
        t_id = str(att.registration.test_id)
        if t_id not in test_rankings_cache:
            test_rankings_cache[t_id] = calculate_candidate_rankings_and_percentiles(t_id)

        r_info = test_rankings_cache[t_id].get(str(att.attempt_id), {})
        att.rank = r_info.get('rank', '—')
        att.percentile = r_info.get('percentile', '—')

    # Clean querystring for export and pagination links (excludes page param)
    params = request.GET.copy()
    if 'page' in params:
        del params['page']
    filter_querystring = params.urlencode()

    context = {
        'page_obj': page_obj,
        'all_tests': all_tests,
        'test_id': test_id,
        'search_query': search_query,
        'status_filter': status_filter,
        'outcome_filter': outcome_filter,
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to': request.GET.get('date_to', '').strip(),
        'total_count': attempts_qs.count(),
        'filter_querystring': filter_querystring,
    }
    return render(request, 'admin_portal/analytics/candidate_performance.html', context)


@admin_required
def question_analysis_report(request):
    """
    Question-Level Analysis Report.
    Calculates per-question accuracy against the authoritative assigned-attempt
    denominator. Highlights difficulty categories and response patterns.
    """
    test_id = request.GET.get('test_id', '').strip()
    search_query = request.GET.get('q', '').strip()
    diff_filter = request.GET.get('difficulty', '').strip()

    all_tests = Test.objects.all().order_by('test_name')
    question_data = get_question_analysis_analytics(test_id=test_id or None)

    # Apply text and difficulty filters
    if search_query:
        question_data = [
            q for q in question_data
            if search_query.lower() in q['question'].question_text.lower()
            or search_query.lower() in q['question'].topic.lower()
        ]

    if diff_filter:
        question_data = [
            q for q in question_data
            if q['question'].difficulty.lower() == diff_filter.lower()
        ]

    # Paginate list
    paginator = Paginator(question_data, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'all_tests': all_tests,
        'test_id': test_id,
        'search_query': search_query,
        'diff_filter': diff_filter,
        'total_questions': len(question_data),
    }
    return render(request, 'admin_portal/analytics/question_analysis.html', context)


@admin_required
def topic_performance_report(request):
    """
    Topic-Wise Performance and Improvement Report.
    Groups candidate response accuracies by topic, highlighting proficiencies
    and curated improvement recommendations.
    """
    test_id = request.GET.get('test_id', '').strip()
    all_tests = Test.objects.all().order_by('test_name')

    topic_data = get_topic_analytics(test_id=test_id or None)

    context = {
        'topic_data': topic_data,
        'all_tests': all_tests,
        'test_id': test_id,
        'total_topics': len(topic_data),
    }
    return render(request, 'admin_portal/analytics/topic_performance.html', context)


@admin_required
def test_completion_report(request):
    """
    Test Completion and Attempt-Pattern Report.
    Visualises mutually exclusive candidate categories in the assessment pipeline
    and audits recorded integrity events.
    """
    test_id = request.GET.get('test_id', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    filters = {'date_from': date_from, 'date_to': date_to}
    completion_data = get_completion_analytics(test_id=test_id or None, filters=filters)
    all_tests = Test.objects.all().order_by('test_name')

    # Pipeline candidate details table
    regs_qs = TestRegistration.objects.select_related('candidate', 'test').order_by('-registered_at')
    if test_id:
        regs_qs = regs_qs.filter(test_id=test_id)

    paginator = Paginator(regs_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    for reg in page_obj:
        try:
            reg.attempt_obj = reg.attempt
        except Exception:
            reg.attempt_obj = None

    context = {
        'completion_data': completion_data,
        'all_tests': all_tests,
        'test_id': test_id,
        'date_from': date_from,
        'date_to': date_to,
        'page_obj': page_obj,
    }
    return render(request, 'admin_portal/analytics/completion_report.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# BATCH CSV EXPORT CONTROLLERS (Formula Injection Protected)
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def export_test_summary_csv(request, test_id=None):
    """
    Export Test Summary Report to CSV.
    Protected against Spreadsheet Formula Injection.
    """
    filters = {
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to': request.GET.get('date_to', '').strip(),
    }

    if test_id:
        summaries = [get_test_summary_analytics(test_id=test_id, filters=filters)]
        filename = f"HireScan_Test_Summary_{test_id}.csv"
    else:
        summaries = get_test_summary_analytics(filters=filters)
        filename = "HireScan_All_Tests_Summary.csv"

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Test ID', 'Test Name', 'Status', 'Duration (mins)', 'Questions Configured',
        'Passing Marks', 'Total Registered', 'Candidates Started', 'Not Started',
        'Completed', 'Timed Out', 'In Progress', 'Passed', 'Failed', 'Pass Rate (%)',
        'Average Score', 'Highest Score', 'Lowest Score', 'Average Percentage',
        'Average Time Taken'
    ])

    for item in summaries:
        if not item:
            continue
        t = item['test']
        writer.writerow([
            sanitize_csv_cell(t.test_id),
            sanitize_csv_cell(t.test_name),
            sanitize_csv_cell('Active' if t.is_active else 'Inactive'),
            sanitize_csv_cell(t.duration_minutes),
            sanitize_csv_cell(t.total_questions),
            sanitize_csv_cell(t.passing_marks),
            sanitize_csv_cell(item['total_registered']),
            sanitize_csv_cell(item['started']),
            sanitize_csv_cell(item['not_started']),
            sanitize_csv_cell(item['completed']),
            sanitize_csv_cell(item['expired']),
            sanitize_csv_cell(item['in_progress']),
            sanitize_csv_cell(item['passed']),
            sanitize_csv_cell(item['failed']),
            sanitize_csv_cell(f"{item['pass_rate']}%"),
            sanitize_csv_cell(item['avg_score']),
            sanitize_csv_cell(item['max_score']),
            sanitize_csv_cell(item['min_score']),
            sanitize_csv_cell(f"{item['avg_percentage']}%"),
            sanitize_csv_cell(item['avg_time_formatted']),
        ])

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_csv',
        activity_details=f"Admin exported Test Summary CSV report ({filename})."
    )

    return response


@admin_required
def export_candidates_csv(request):
    """
    Export Candidate Performance Results to CSV with Ranks & Percentiles.
    Applies the exact active filters as the report view.
    """
    test_id = request.GET.get('test_id', '').strip()
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    outcome_filter = request.GET.get('outcome', '').strip()
    date_from = parse_date_filter(request.GET.get('date_from', '').strip())
    date_to = parse_date_filter(request.GET.get('date_to', '').strip())

    attempts_qs = TestAttempt.objects.select_related(
        'registration__test', 'registration__candidate'
    ).order_by('-start_time')

    if test_id:
        attempts_qs = attempts_qs.filter(registration__test_id=test_id)
    if search_query:
        attempts_qs = attempts_qs.filter(
            Q(registration__candidate__name__icontains=search_query) |
            Q(registration__candidate__email__icontains=search_query)
        )
    if status_filter:
        attempts_qs = attempts_qs.filter(status=status_filter)
    if outcome_filter == 'passed':
        attempts_qs = attempts_qs.filter(is_passed=True)
    elif outcome_filter == 'failed':
        attempts_qs = attempts_qs.filter(is_passed=False)
    if date_from:
        attempts_qs = attempts_qs.filter(start_time__date__gte=date_from)
    if date_to:
        attempts_qs = attempts_qs.filter(start_time__date__lte=date_to)

    # Precalculate rankings
    test_rankings_cache = {}

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="HireScan_Candidate_Performance.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Attempt ID', 'Candidate Name', 'Candidate Email', 'Test Name', 'Status',
        'Submission Mode', 'Score', 'Total Questions', 'Percentage', 'Outcome',
        'Cohort Rank', 'Cohort Percentile', 'Correct Answers', 'Incorrect Answers',
        'Unanswered', 'Time Taken (sec)', 'Started At', 'Submitted At'
    ])

    for att in attempts_qs:
        t_id = str(att.registration.test_id)
        if t_id not in test_rankings_cache:
            test_rankings_cache[t_id] = calculate_candidate_rankings_and_percentiles(t_id)

        r_info = test_rankings_cache[t_id].get(str(att.attempt_id), {})
        rank = r_info.get('rank', '—')
        pctile = r_info.get('percentile', '—')

        outcome = 'Passed' if att.is_passed is True else ('Failed' if att.is_passed is False else 'Pending')

        writer.writerow([
            sanitize_csv_cell(att.attempt_id),
            sanitize_csv_cell(att.registration.candidate.name),
            sanitize_csv_cell(att.registration.candidate.email),
            sanitize_csv_cell(att.registration.test.test_name),
            sanitize_csv_cell(att.status.title()),
            sanitize_csv_cell(att.submission_reason.title() if att.submission_reason else '—'),
            sanitize_csv_cell(att.score if att.score is not None else '—'),
            sanitize_csv_cell(att.total_questions),
            sanitize_csv_cell(f"{att.percentage}%" if att.percentage is not None else '—'),
            sanitize_csv_cell(outcome),
            sanitize_csv_cell(rank),
            sanitize_csv_cell(f"{pctile}%" if pctile != '—' else '—'),
            sanitize_csv_cell(att.correct_answers),
            sanitize_csv_cell(att.incorrect_answers),
            sanitize_csv_cell(att.unanswered),
            sanitize_csv_cell(att.time_taken_seconds or 0),
            sanitize_csv_cell(att.start_time.strftime("%Y-%m-%d %H:%M:%S")),
            sanitize_csv_cell(att.end_time.strftime("%Y-%m-%d %H:%M:%S") if att.end_time else '—'),
        ])

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_csv',
        activity_details=f"Admin exported Candidate Performance CSV report ({attempts_qs.count()} rows)."
    )

    return response


@admin_required
def export_questions_csv(request):
    """Export Question-Level Analysis to CSV."""
    test_id = request.GET.get('test_id', '').strip()
    question_data = get_question_analysis_analytics(test_id=test_id or None)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="HireScan_Question_Analysis.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Question ID', 'Test Name', 'Topic', 'Difficulty', 'Question Text',
        'Finalized Attempts Assigned', 'Correct Responses', 'Incorrect Responses',
        'Unanswered Responses', 'Accuracy Rate (%)', 'Difficulty Assessment'
    ])

    for item in question_data:
        q = item['question']
        writer.writerow([
            sanitize_csv_cell(q.question_id),
            sanitize_csv_cell(q.test.test_name),
            sanitize_csv_cell(q.topic),
            sanitize_csv_cell(q.difficulty.title()),
            sanitize_csv_cell(q.question_text),
            sanitize_csv_cell(item['assigned_count']),
            sanitize_csv_cell(item['correct_count']),
            sanitize_csv_cell(item['incorrect_count']),
            sanitize_csv_cell(item['unanswered_count']),
            sanitize_csv_cell(f"{item['accuracy']}%" if item['has_data'] else 'No Data'),
            sanitize_csv_cell(item['diff_level']),
        ])

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_csv',
        activity_details=f"Admin exported Question Analysis CSV report ({len(question_data)} questions)."
    )

    return response


@admin_required
def export_topics_csv(request):
    """Export Topic-Level Competency Analysis to CSV."""
    test_id = request.GET.get('test_id', '').strip()
    topic_data = get_topic_analytics(test_id=test_id or None)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="HireScan_Topic_Performance.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Topic / Domain', 'Questions in Bank', 'Total Appearances', 'Correct Answers',
        'Incorrect Answers', 'Unanswered Questions', 'Accuracy Rate (%)',
        'Proficiency Classification', 'Recommended Study Focus'
    ])

    for item in topic_data:
        suggestions_str = "; ".join(item['suggestions']) if item['suggestions'] else 'None'
        writer.writerow([
            sanitize_csv_cell(item['topic']),
            sanitize_csv_cell(item['question_bank_count']),
            sanitize_csv_cell(item['assigned_count']),
            sanitize_csv_cell(item['correct_count']),
            sanitize_csv_cell(item['incorrect_count']),
            sanitize_csv_cell(item['unanswered_count']),
            sanitize_csv_cell(f"{item['accuracy']}%"),
            sanitize_csv_cell(item['level']),
            sanitize_csv_cell(suggestions_str),
        ])

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_csv',
        activity_details=f"Admin exported Topic Performance CSV report ({len(topic_data)} topics)."
    )

    return response


@admin_required
def export_completion_csv(request):
    """Export Candidate Pipeline Completion Status to CSV."""
    test_id = request.GET.get('test_id', '').strip()
    date_from = parse_date_filter(request.GET.get('date_from', '').strip())
    date_to = parse_date_filter(request.GET.get('date_to', '').strip())

    regs_qs = TestRegistration.objects.select_related('candidate', 'test').order_by('-registered_at')
    if test_id:
        regs_qs = regs_qs.filter(test_id=test_id)
    if date_from:
        regs_qs = regs_qs.filter(registered_at__date__gte=date_from)
    if date_to:
        regs_qs = regs_qs.filter(registered_at__date__lte=date_to)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="HireScan_Test_Completion_Pipeline.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Registration ID', 'Candidate Name', 'Candidate Email', 'Test Name',
        'Registered Date', 'Pipeline Status', 'Attempt Status', 'Submission Mode',
        'Score', 'Percentage', 'Outcome'
    ])

    for reg in regs_qs:
        attempt = None
        try:
            attempt = reg.attempt
        except Exception:
            attempt = None

        if reg.status == 'cancelled':
            pipeline_status = 'Cancelled'
        elif attempt is None:
            pipeline_status = 'Registered (Not Started)'
        elif attempt.status == 'in_progress':
            pipeline_status = 'In Progress'
        elif attempt.status == 'completed':
            pipeline_status = 'Completed'
        else:
            pipeline_status = 'Timed Out'

        att_status = attempt.status.title() if attempt else 'None'
        sub_mode = attempt.submission_reason.title() if attempt and attempt.submission_reason else '—'
        score_val = attempt.score if attempt and attempt.score is not None else '—'
        pct_val = f"{attempt.percentage}%" if attempt and attempt.percentage is not None else '—'
        outcome = ('Passed' if attempt.is_passed else 'Failed') if attempt and attempt.is_passed is not None else '—'

        writer.writerow([
            sanitize_csv_cell(reg.registration_id),
            sanitize_csv_cell(reg.candidate.name),
            sanitize_csv_cell(reg.candidate.email),
            sanitize_csv_cell(reg.test.test_name),
            sanitize_csv_cell(reg.registered_at.strftime("%Y-%m-%d %H:%M")),
            sanitize_csv_cell(pipeline_status),
            sanitize_csv_cell(att_status),
            sanitize_csv_cell(sub_mode),
            sanitize_csv_cell(score_val),
            sanitize_csv_cell(pct_val),
            sanitize_csv_cell(outcome),
        ])

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_csv',
        activity_details=f"Admin exported Completion Pipeline CSV report ({regs_qs.count()} registrations)."
    )

    return response


@admin_required
def export_test_summary_pdf(request, test_id):
    """
    Download official executive assessment summary report in PDF format.
    Restricted to authorized administrators.
    """
    import re
    from assessments.models import Test
    from analytics.pdf_export import generate_assessment_summary_pdf

    test = get_object_or_404(Test, test_id=test_id)
    pdf_bytes = generate_assessment_summary_pdf(test.test_id)

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_pdf',
        activity_details=f"Admin exported Assessment Summary PDF report for '{test.test_name}'."
    )

    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', test.test_name)[:30]
    filename = f"HireScan_Assessment_Summary_{safe_title}.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@admin_required
def export_candidate_results_pdf(request):
    """
    Download official examinee assessment results and cohort outcomes in PDF format.
    Respects active search, assessment selection, outcome, and date filters.
    Restricted to authorized administrators.
    """
    import re
    from assessments.models import Test
    from analytics.pdf_export import generate_candidate_results_pdf

    test_id = request.GET.get('test_id', '').strip()
    filters = {
        'q': request.GET.get('q', '').strip(),
        'status': request.GET.get('status', '').strip(),
        'outcome': request.GET.get('outcome', '').strip(),
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to': request.GET.get('date_to', '').strip(),
    }

    test_obj = None
    if test_id:
        test_obj = get_object_or_404(Test, test_id=test_id)

    pdf_bytes = generate_candidate_results_pdf(test_id=test_id or None, filters=filters)

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='report_exported_pdf',
        activity_details="Admin exported Examinee Assessment Results PDF report."
    )

    if test_obj:
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', test_obj.test_name)[:25]
        filename = f"HireScan_Examinees_{safe_name}.pdf"
    else:
        filename = "HireScan_All_Examinees_Results.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
