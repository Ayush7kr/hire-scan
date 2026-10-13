from django.shortcuts import render
from django.db.models import Count, Avg, Q
from accounts.decorators import admin_required
from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, TestRegistration
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
    completed_attempts = TestAttempt.objects.filter(status='completed').count()

    # Recent activity log
    recent_activity = ActivityLog.objects.select_related('admin', 'candidate', 'attempt').order_by('-occurred_at')[:10]

    # Test performance overview
    tests = Test.objects.all().order_by('-created_at')[:5]
    test_summaries = []
    for test in tests:
        reg_count = TestRegistration.objects.filter(test=test).count()
        attempts = TestAttempt.objects.filter(registration__test=test, status='completed')
        comp_count = attempts.count()
        avg_score = attempts.aggregate(Avg('percentage'))['percentage__avg'] or 0
        passed_count = attempts.filter(is_passed=True).count()
        pass_rate = round((passed_count / comp_count * 100), 1) if comp_count > 0 else 0

        test_summaries.append({
            'test': test,
            'registrations': reg_count,
            'completed': comp_count,
            'avg_score': round(avg_score, 1),
            'pass_rate': pass_rate,
        })

    context = {
        'admin_user': request.admin_user,
        'total_candidates': total_candidates,
        'total_tests': total_tests,
        'active_tests': active_tests,
        'completed_attempts': completed_attempts,
        'recent_activity': recent_activity,
        'test_summaries': test_summaries,
    }
    return render(request, 'admin_portal/dashboard.html', context)
