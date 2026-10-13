from django.shortcuts import render
from django.db.models import Count, Avg, Q
from accounts.decorators import admin_required
from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration
from attempts.models import TestAttempt


@admin_required
def admin_dashboard(request):
    """
    Administrator Dashboard.
    Provides key system metrics, recent activity feed, and test performance overview.
    All data is computed dynamically from real database records.
    """
    total_candidates = Candidate.objects.count()
    total_tests = Test.objects.count()
    active_tests = Test.objects.filter(is_active=True).count()
    total_registrations = TestRegistration.objects.count()
    completed_attempts = TestAttempt.objects.filter(status='completed').count()

    # Calculate tests with insufficient question banks
    all_tests = Test.objects.all()
    insufficient_tests_count = 0
    for t in all_tests:
        b_count = Question.objects.filter(test=t).count()
        if b_count < t.total_questions:
            insufficient_tests_count += 1

    # Recent activity log
    recent_activity = ActivityLog.objects.select_related('admin', 'candidate', 'attempt').order_by('-occurred_at')[:10]

    # Test performance overview
    tests = Test.objects.all().order_by('-created_at')[:6]
    test_summaries = []
    for test in tests:
        reg_count = TestRegistration.objects.filter(test=test).count()
        attempts = TestAttempt.objects.filter(registration__test=test, status='completed')
        comp_count = attempts.count()
        avg_score = attempts.aggregate(Avg('percentage'))['percentage__avg'] or 0
        passed_count = attempts.filter(is_passed=True).count()
        pass_rate = round((passed_count / comp_count * 100), 1) if comp_count > 0 else 0
        bank_count = Question.objects.filter(test=test).count()

        test_summaries.append({
            'test': test,
            'bank_count': bank_count,
            'registrations': reg_count,
            'completed': comp_count,
            'avg_score': round(avg_score, 1),
            'pass_rate': pass_rate,
            'is_sufficient': bank_count >= test.total_questions,
        })

    context = {
        'admin_user': request.admin_user,
        'total_candidates': total_candidates,
        'total_tests': total_tests,
        'active_tests': active_tests,
        'total_registrations': total_registrations,
        'insufficient_tests_count': insufficient_tests_count,
        'completed_attempts': completed_attempts,
        'recent_activity': recent_activity,
        'test_summaries': test_summaries,
    }
    return render(request, 'admin_portal/dashboard.html', context)
