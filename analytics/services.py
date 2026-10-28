"""
Analytics and Reporting Service for HireScan.

Provides calculation logic for administrator dashboards, test summaries,
candidate performance rankings, question-level analysis, topic performance,
and formula-injection safe CSV generation.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.db.models import Count, Avg, Min, Max, Q, F
from django.utils import timezone

from accounts.models import Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration, NotificationLog
from attempts.models import TestAttempt, AttemptQuestion


def sanitize_csv_cell(value):
    """
    Guard against Spreadsheet Formula Injection (CSV Injection).
    Values beginning with '=', '+', '-', '@', '\t', '\r' are prefixed with a
    single quote so spreadsheet software treats them as literal strings.
    """
    if value is None:
        return ""
    val_str = str(value).replace("\x00", "")
    if val_str and val_str[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{val_str}"
    return val_str


def parse_date_filter(date_str):
    """Safely parse YYYY-MM-DD date string or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def calculate_candidate_rankings_and_percentiles(test_id):
    """
    Calculates 1-indexed ranks and psychometric percentiles for all finalized
    attempts belonging to a specific test.

    Formula for percentile:
        Percentile = ((B + 0.5 * E) / N) * 100
    where:
        B = count of scores strictly below the candidate
        E = count of scores equal to the candidate (including self)
        N = total finalized attempts for this test

    Ties:
        Rank is standard competition rank (1, 2, 2, 4...).
        Secondary ordering by time_taken_seconds ASC.
    """
    finalized_attempts = list(
        TestAttempt.objects.filter(
            registration__test_id=test_id,
            status__in=['completed', 'expired']
        ).select_related('registration__candidate').order_by(
            '-score', 'time_taken_seconds', 'start_time'
        )
    )

    N = len(finalized_attempts)
    results = {}
    if N == 0:
        return results

    all_scores = [a.score if a.score is not None else 0 for a in finalized_attempts]

    for index, attempt in enumerate(finalized_attempts, start=1):
        cand_score = attempt.score if attempt.score is not None else 0

        # Psychometric percentile requires a comparative cohort (N >= 2).
        # For a single finalized candidate (N=1), a percentile cannot be meaningfully calculated.
        if N > 1:
            B = sum(1 for s in all_scores if s < cand_score)
            E = sum(1 for s in all_scores if s == cand_score)
            percentile = round(((B + 0.5 * E) / N) * 100, 1)
        else:
            percentile = '—'

        # Standard competition rank
        rank = sum(1 for s in all_scores if s > cand_score) + 1

        results[str(attempt.attempt_id)] = {
            'rank': rank,
            'percentile': percentile,
            'cohort_size': N,
            'candidate_name': attempt.registration.candidate.name,
            'candidate_email': attempt.registration.candidate.email,
            'score': cand_score,
            'percentage': attempt.percentage or Decimal('0.00'),
            'time_taken_seconds': attempt.time_taken_seconds or 0,
            'is_passed': attempt.is_passed,
        }

    return results


def get_dashboard_analytics(filters=None):
    """
    Computes system overview metrics and chart dataset payloads for the
    Administrator Analytics Dashboard.

    Supported filters:
      - test_id (UUID string)
      - date_from (YYYY-MM-DD)
      - date_to (YYYY-MM-DD)
      - status ('completed', 'expired', 'in_progress')
    """
    filters = filters or {}
    test_id = filters.get('test_id')
    date_from = parse_date_filter(filters.get('date_from'))
    date_to = parse_date_filter(filters.get('date_to'))
    status_filter = filters.get('status')

    # Base querysets
    tests_qs = Test.objects.all()
    regs_qs = TestRegistration.objects.all()
    attempts_qs = TestAttempt.objects.all().select_related('registration__test', 'registration__candidate')

    # Apply filters
    if test_id:
        tests_qs = tests_qs.filter(test_id=test_id)
        regs_qs = regs_qs.filter(test_id=test_id)
        attempts_qs = attempts_qs.filter(registration__test_id=test_id)

    if date_from:
        attempts_qs = attempts_qs.filter(start_time__date__gte=date_from)
        regs_qs = regs_qs.filter(registered_at__date__gte=date_from)

    if date_to:
        attempts_qs = attempts_qs.filter(start_time__date__lte=date_to)
        regs_qs = regs_qs.filter(registered_at__date__lte=date_to)

    if status_filter:
        attempts_qs = attempts_qs.filter(status=status_filter)

    # Core Counts
    total_candidates = Candidate.objects.count()
    total_tests = Test.objects.count()
    active_tests = Test.objects.filter(is_active=True).count()
    total_registrations = regs_qs.count()
    total_attempts_started = attempts_qs.count()

    finalized_attempts = attempts_qs.filter(status__in=['completed', 'expired'])
    finalized_count = finalized_attempts.count()
    completed_count = attempts_qs.filter(status='completed').count()
    expired_count = attempts_qs.filter(status='expired').count()
    in_progress_count = attempts_qs.filter(status='in_progress').count()

    passed_count = finalized_attempts.filter(is_passed=True).count()
    failed_count = finalized_attempts.filter(is_passed=False).count()

    # Pass Rate = (Passed Finalized Attempts / All Finalized Attempts) * 100
    overall_pass_rate = (
        round((passed_count / finalized_count) * 100, 1)
        if finalized_count > 0 else 0.0
    )

    # Average Score and Percentage based strictly on finalized attempts
    avg_score_agg = finalized_attempts.aggregate(Avg('score'))['score__avg']
    avg_score = round(avg_score_agg, 1) if avg_score_agg is not None else 0.0

    avg_pct_agg = finalized_attempts.aggregate(Avg('percentage'))['percentage__avg']
    avg_percentage = round(avg_pct_agg, 1) if avg_pct_agg is not None else 0.0

    completion_rate = (
        round((finalized_count / total_registrations) * 100, 1)
        if total_registrations > 0 else 0.0
    )

    # Operational Dashboard Indicators
    now_dt = timezone.now()
    upcoming_assessments_count = tests_qs.filter(
        is_cancelled=False, is_active=True, start_time__gt=now_dt
    ).count()

    in_progress_assessments_count = tests_qs.filter(
        is_cancelled=False, is_active=True
    ).filter(
        Q(start_time__isnull=True) | Q(start_time__lte=now_dt)
    ).filter(
        Q(end_time__isnull=True) | Q(end_time__gte=now_dt)
    ).count()

    recently_completed_assessments_count = tests_qs.filter(
        is_cancelled=False
    ).filter(
        Q(end_time__isnull=False, end_time__lt=now_dt) |
        (Q(is_active=False) & Q(registrations__attempt__status='completed'))
    ).distinct().count()

    registrations_awaiting_count = regs_qs.filter(
        status='registered', attempt__isnull=True
    ).count()

    failed_notifications_count = NotificationLog.objects.filter(status='failed').count()

    # ─────────────────────────────────────────────────────────────
    # CHART 1: Attempts Over Time (Daily timeline)
    # ─────────────────────────────────────────────────────────────
    # Group by date for last 14 days or filtered period
    if date_from and date_to:
        start_d = date_from
        end_d = date_to
    else:
        end_d = timezone.now().date()
        start_d = end_d - timedelta(days=13)

    daily_labels = []
    daily_started = []
    daily_completed = []

    # Pre-fetch counts grouped by date
    cur_d = start_d
    max_days = min(60, (end_d - start_d).days + 1)
    for _ in range(max_days):
        label_str = cur_d.strftime("%b %d")
        daily_labels.append(label_str)
        s_cnt = attempts_qs.filter(start_time__date=cur_d).count()
        c_cnt = attempts_qs.filter(end_time__date=cur_d, status__in=['completed', 'expired']).count()
        daily_started.append(s_cnt)
        daily_completed.append(c_cnt)
        cur_d += timedelta(days=1)

    # ─────────────────────────────────────────────────────────────
    # CHART 2: Pass / Fail Distribution
    # ─────────────────────────────────────────────────────────────
    pass_fail_chart = {
        'labels': ['Passed', 'Failed'],
        'data': [passed_count, failed_count],
        'colors': ['#10b981', '#ef4444'],
    }

    # ─────────────────────────────────────────────────────────────
    # CHART 3: Average Score by Test (Top tests)
    # ─────────────────────────────────────────────────────────────
    test_score_labels = []
    test_score_data = []
    for t in tests_qs[:10]:
        t_final = finalized_attempts.filter(registration__test=t)
        t_avg = t_final.aggregate(Avg('percentage'))['percentage__avg']
        test_score_labels.append(t.test_name[:20] + ('...' if len(t.test_name) > 20 else ''))
        test_score_data.append(float(round(t_avg, 1)) if t_avg is not None else 0.0)

    # ─────────────────────────────────────────────────────────────
    # CHART 4: Score Distribution Buckets (0-19%, 20-39%, etc.)
    # ─────────────────────────────────────────────────────────────
    buckets = [
        ('0-19%', 0, 19.99),
        ('20-39%', 20, 39.99),
        ('40-59%', 40, 59.99),
        ('60-79%', 60, 79.99),
        ('80-100%', 80, 100.0),
    ]
    bucket_labels = [b[0] for b in buckets]
    bucket_counts = []
    for _, low, high in buckets:
        cnt = finalized_attempts.filter(percentage__gte=low, percentage__lte=high).count()
        bucket_counts.append(cnt)

    # ─────────────────────────────────────────────────────────────
    # CHART 5: Topic-Wise Accuracy
    # ─────────────────────────────────────────────────────────────
    topic_data = get_topic_analytics(test_id=test_id)
    topic_labels = [t['topic'][:18] for t in topic_data[:8]]
    topic_accuracies = [float(t['accuracy']) for t in topic_data[:8]]


    # ─────────────────────────────────────────────────────────────
    # CHART 6: Test Completion Pipeline Status
    # ─────────────────────────────────────────────────────────────
    # Not started = registrations that have no attempt
    not_started_count = regs_qs.filter(attempt__isnull=True).count()
    pipeline_labels = ['Not Started', 'In Progress', 'Completed', 'Timed Out']
    pipeline_counts = [not_started_count, in_progress_count, completed_count, expired_count]

    return {
        'total_candidates': total_candidates,
        'total_tests': total_tests,
        'active_tests': active_tests,
        'total_registrations': total_registrations,
        'total_attempts_started': total_attempts_started,
        'finalized_count': finalized_count,
        'completed_count': completed_count,
        'expired_count': expired_count,
        'in_progress_count': in_progress_count,
        'passed_count': passed_count,
        'failed_count': failed_count,
        'overall_pass_rate': overall_pass_rate,
        'avg_score': avg_score,
        'avg_percentage': avg_percentage,
        'completion_rate': completion_rate,
        # Operational Indicators
        'upcoming_assessments_count': upcoming_assessments_count,
        'in_progress_assessments_count': in_progress_assessments_count,
        'recently_completed_assessments_count': recently_completed_assessments_count,
        'registrations_awaiting_count': registrations_awaiting_count,
        'failed_notifications_count': failed_notifications_count,
        # Chart payloads
        'daily_labels': daily_labels,
        'daily_started': daily_started,
        'daily_completed': daily_completed,
        'pass_fail_chart': pass_fail_chart,
        'test_score_labels': test_score_labels,
        'test_score_data': test_score_data,
        'bucket_labels': bucket_labels,
        'bucket_counts': bucket_counts,
        'topic_labels': topic_labels,
        'topic_accuracies': topic_accuracies,
        'pipeline_labels': pipeline_labels,
        'pipeline_counts': pipeline_counts,
    }


def get_test_summary_analytics(test_id=None, filters=None):
    """
    Returns high-level and detailed metrics for tests.
    If test_id is given, returns single test breakdown.
    If None, returns list of summaries for all tests.
    """
    filters = filters or {}
    date_from = parse_date_filter(filters.get('date_from'))
    date_to = parse_date_filter(filters.get('date_to'))

    tests_qs = Test.objects.all().order_by('-created_at')
    if test_id:
        tests_qs = tests_qs.filter(test_id=test_id)

    summaries = []
    for test in tests_qs:
        regs = TestRegistration.objects.filter(test=test)
        attempts = TestAttempt.objects.filter(registration__test=test)

        if date_from:
            attempts = attempts.filter(start_time__date__gte=date_from)
            regs = regs.filter(registered_at__date__gte=date_from)
        if date_to:
            attempts = attempts.filter(start_time__date__lte=date_to)
            regs = regs.filter(registered_at__date__lte=date_to)

        total_reg = regs.count()
        started = attempts.count()
        not_started = regs.filter(attempt__isnull=True).count()
        completed = attempts.filter(status='completed').count()
        expired = attempts.filter(status='expired').count()
        in_progress = attempts.filter(status='in_progress').count()
        finalized = attempts.filter(status__in=['completed', 'expired'])
        finalized_count = finalized.count()

        passed = finalized.filter(is_passed=True).count()
        failed = finalized.filter(is_passed=False).count()
        pass_rate = round((passed / finalized_count) * 100, 1) if finalized_count > 0 else 0.0

        score_agg = finalized.aggregate(
            avg_score=Avg('score'),
            min_score=Min('score'),
            max_score=Max('score'),
            avg_pct=Avg('percentage'),
            avg_time=Avg('time_taken_seconds')
        )

        avg_score = round(score_agg['avg_score'], 1) if score_agg['avg_score'] is not None else 0.0
        min_score = score_agg['min_score'] if score_agg['min_score'] is not None else 0
        max_score = score_agg['max_score'] if score_agg['max_score'] is not None else 0
        avg_pct = round(score_agg['avg_pct'], 1) if score_agg['avg_pct'] is not None else 0.0
        avg_time = int(score_agg['avg_time']) if score_agg['avg_time'] is not None else 0

        mins = avg_time // 60
        secs = avg_time % 60
        avg_time_formatted = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        bank_count = Question.objects.filter(test=test).count()

        # Statistical distribution calculations
        scores_list = [a.score for a in finalized if a.score is not None]
        scores_list.sort()
        if scores_list:
            n_scores = len(scores_list)
            mid = n_scores // 2
            if n_scores % 2 == 1:
                median_score = float(scores_list[mid])
            else:
                median_score = round(float((scores_list[mid - 1] + scores_list[mid]) / 2), 1)
            score_range = max_score - min_score
            if n_scores >= 2:
                mean_s = sum(scores_list) / n_scores
                var_s = sum((x - mean_s) ** 2 for x in scores_list) / (n_scores - 1)
                std_dev = round(var_s ** 0.5, 2)
            else:
                std_dev = 0.0
        else:
            median_score = 0.0
            score_range = 0
            std_dev = 0.0

        # Score percentage distribution buckets - strictly partitioned so every finalized examinee belongs to exactly one bracket
        b_above_90 = 0
        b_75_89 = 0
        b_50_74 = 0
        b_below_50 = 0
        for a in finalized:
            pct = float(a.percentage) if a.percentage is not None else 0.0
            if pct >= 90.0:
                b_above_90 += 1
            elif pct >= 75.0:
                b_75_89 += 1
            elif pct >= 50.0:
                b_50_74 += 1
            else:
                b_below_50 += 1

        distribution_buckets = [
            {'label': 'Excellent (90–100%)', 'count': b_above_90, 'pct': round((b_above_90 / finalized_count) * 100, 1) if finalized_count > 0 else 0.0, 'color': 'success'},
            {'label': 'Proficient (75–89%)', 'count': b_75_89, 'pct': round((b_75_89 / finalized_count) * 100, 1) if finalized_count > 0 else 0.0, 'color': 'primary'},
            {'label': 'Average (50–74%)', 'count': b_50_74, 'pct': round((b_50_74 / finalized_count) * 100, 1) if finalized_count > 0 else 0.0, 'color': 'warning'},
            {'label': 'Below Standard (<50%)', 'count': b_below_50, 'pct': round((b_below_50 / finalized_count) * 100, 1) if finalized_count > 0 else 0.0, 'color': 'danger'},
        ]

        summaries.append({
            'test': test,
            'total_registered': total_reg,
            'started': started,
            'not_started': not_started,
            'completed': completed,
            'expired': expired,
            'in_progress': in_progress,
            'finalized_count': finalized_count,
            'passed': passed,
            'failed': failed,
            'pass_rate': pass_rate,
            'avg_score': avg_score,
            'median_score': median_score,
            'score_range': score_range,
            'std_dev_score': std_dev,
            'min_score': min_score,
            'max_score': max_score,
            'avg_percentage': avg_pct,
            'avg_time_seconds': avg_time,
            'avg_time_formatted': avg_time_formatted,
            'bank_count': bank_count,
            'is_sufficient': bank_count >= test.total_questions,
            'distribution_buckets': distribution_buckets,
            'topic_breakdown': get_topic_analytics(test_id=test.test_id),
        })

    if test_id:
        return summaries[0] if summaries else None
    return summaries


def get_question_analysis_analytics(test_id=None):
    """
    Computes per-question accuracy metrics across finalized attempts.

    Critical Denominator Rule:
        Question accuracy denominator is strictly the number of finalized
        attempts in which the question was ACTUALLY assigned (via AttemptQuestion),
        NOT the total registered candidate count.
    """
    questions_qs = Question.objects.select_related('test').all()
    if test_id:
        questions_qs = questions_qs.filter(test_id=test_id)

    questions_qs = questions_qs.order_by('test__test_name', 'created_at')

    analysis = []
    for q in questions_qs:
        # All assigned occurrences in finalized attempts
        aq_qs = AttemptQuestion.objects.filter(
            question=q,
            attempt__status__in=['completed', 'expired']
        )

        assigned_count = aq_qs.count()
        correct_count = aq_qs.filter(is_correct=True).count()
        incorrect_count = aq_qs.filter(is_correct=False, selected_option__isnull=False).count()
        unanswered_count = aq_qs.filter(selected_option__isnull=True).count()

        if assigned_count > 0:
            accuracy = round((correct_count / assigned_count) * 100, 1)
            facility_index = round(correct_count / assigned_count, 2)
        else:
            accuracy = None
            facility_index = None

        # Discrimination Index: compare top group vs bottom group of finalized attempts
        discrimination_index = None
        discrimination_display = "— (Cohort < 4)"
        if assigned_count >= 4:
            ranked_aq = list(aq_qs.select_related('attempt').order_by('-attempt__score'))
            group_size = max(1, int(round(len(ranked_aq) * 0.27))) if len(ranked_aq) >= 8 else max(1, len(ranked_aq) // 2)
            upper_group = ranked_aq[:group_size]
            lower_group = ranked_aq[-group_size:]

            p_upper = sum(1 for a in upper_group if a.is_correct) / len(upper_group)
            p_lower = sum(1 for a in lower_group if a.is_correct) / len(lower_group)
            d_val = round(p_upper - p_lower, 2)
            discrimination_index = d_val
            if d_val >= 0.40:
                discrimination_display = f"{d_val:+.2f} (Excellent)"
            elif d_val >= 0.20:
                discrimination_display = f"{d_val:+.2f} (Good)"
            elif d_val >= 0.0:
                discrimination_display = f"{d_val:+.2f} (Fair)"
            else:
                discrimination_display = f"{d_val:+.2f} (Review)"

        # Difficulty index interpretation
        if assigned_count == 0:
            diff_level = 'No Attempt Data'
            badge_class = 'bg-secondary-subtle text-secondary'
        elif accuracy < 40.0:
            diff_level = 'Low Accuracy'
            badge_class = 'bg-danger-subtle text-danger border border-danger-subtle'
        elif accuracy > 75.0:
            diff_level = 'High Accuracy'
            badge_class = 'bg-success-subtle text-success border border-success-subtle'
        else:
            diff_level = 'Balanced'
            badge_class = 'bg-primary-subtle text-primary border border-primary-subtle'

        analysis.append({
            'question': q,
            'assigned_count': assigned_count,
            'correct_count': correct_count,
            'incorrect_count': incorrect_count,
            'unanswered_count': unanswered_count,
            'accuracy': accuracy if accuracy is not None else 0.0,
            'facility_index': facility_index,
            'facility_display': f"{facility_index:.2f}" if facility_index is not None else "—",
            'discrimination_index': discrimination_index,
            'discrimination_display': discrimination_display,
            'has_data': assigned_count > 0,
            'diff_level': diff_level,
            'badge_class': badge_class,
        })

    return analysis


def get_topic_analytics(test_id=None):
    """
    Aggregates topic-level performance metrics and collected improvement suggestions
    across finalized assessment attempts.
    """
    questions_qs = Question.objects.all()
    if test_id:
        questions_qs = questions_qs.filter(test_id=test_id)

    # Collect topics
    topics_map = {}
    for q in questions_qs:
        t_name = q.topic or 'General'
        if t_name not in topics_map:
            topics_map[t_name] = {
                'topic': t_name,
                'question_bank_count': 0,
                'assigned_count': 0,
                'correct_count': 0,
                'incorrect_count': 0,
                'unanswered_count': 0,
                'suggestions': set(),
            }
        topics_map[t_name]['question_bank_count'] += 1
        if q.suggestions:
            topics_map[t_name]['suggestions'].add(q.suggestions.strip())

    # Populate attempt responses
    aq_qs = AttemptQuestion.objects.filter(
        attempt__status__in=['completed', 'expired']
    ).select_related('question')

    if test_id:
        aq_qs = aq_qs.filter(attempt__registration__test_id=test_id)

    for aq in aq_qs:
        t_name = aq.question.topic or 'General'
        if t_name not in topics_map:
            topics_map[t_name] = {
                'topic': t_name,
                'question_bank_count': 0,
                'assigned_count': 0,
                'correct_count': 0,
                'incorrect_count': 0,
                'unanswered_count': 0,
                'suggestions': set(),
            }

        topics_map[t_name]['assigned_count'] += 1
        if aq.is_correct:
            topics_map[t_name]['correct_count'] += 1
        elif aq.selected_option is None:
            topics_map[t_name]['unanswered_count'] += 1
        else:
            topics_map[t_name]['incorrect_count'] += 1

    results = []
    for topic_item in topics_map.values():
        assigned = topic_item['assigned_count']
        correct = topic_item['correct_count']
        accuracy = round((correct / assigned) * 100, 1) if assigned > 0 else 0.0

        if assigned == 0:
            level = 'No Data'
            badge_class = 'bg-secondary-subtle text-secondary'
        elif accuracy >= 75.0:
            level = 'Proficient'
            badge_class = 'bg-success-subtle text-success border border-success-subtle'
        elif accuracy >= 50.0:
            level = 'Average'
            badge_class = 'bg-warning-subtle text-warning border border-warning-subtle'
        else:
            level = 'Needs Work'
            badge_class = 'bg-danger-subtle text-danger border border-danger-subtle'

        results.append({
            'topic': topic_item['topic'],
            'question_bank_count': topic_item['question_bank_count'],
            'assigned_count': assigned,
            'correct_count': correct,
            'incorrect_count': topic_item['incorrect_count'],
            'unanswered_count': topic_item['unanswered_count'],
            'accuracy': accuracy,
            'level': level,
            'badge_class': badge_class,
            'suggestions': sorted(list(topic_item['suggestions'])),
        })

    results.sort(key=lambda x: x['accuracy'])
    return results


def get_completion_analytics(test_id=None, filters=None):
    """
    Computes mutually exclusive pipeline counts for registrations and attempts,
    plus activity audit counts.
    """
    filters = filters or {}
    date_from = parse_date_filter(filters.get('date_from'))
    date_to = parse_date_filter(filters.get('date_to'))

    regs_qs = TestRegistration.objects.select_related('candidate', 'test').all()
    attempts_qs = TestAttempt.objects.select_related('registration__candidate', 'registration__test').all()
    activities_qs = ActivityLog.objects.all()

    if test_id:
        regs_qs = regs_qs.filter(test_id=test_id)
        attempts_qs = attempts_qs.filter(registration__test_id=test_id)
        activities_qs = activities_qs.filter(attempt__registration__test_id=test_id)

    if date_from:
        regs_qs = regs_qs.filter(registered_at__date__gte=date_from)
        attempts_qs = attempts_qs.filter(start_time__date__gte=date_from)
        activities_qs = activities_qs.filter(occurred_at__date__gte=date_from)

    if date_to:
        regs_qs = regs_qs.filter(registered_at__date__lte=date_to)
        attempts_qs = attempts_qs.filter(start_time__date__lte=date_to)
        activities_qs = activities_qs.filter(occurred_at__date__lte=date_to)

    total_regs = regs_qs.count()
    cancelled_regs = regs_qs.filter(status='cancelled').count()
    active_regs = regs_qs.filter(status='registered')

    # Mutually exclusive pipeline categories:
    not_started = active_regs.filter(attempt__isnull=True).count()
    in_progress = attempts_qs.filter(status='in_progress').count()
    completed_manual = attempts_qs.filter(status='completed', submission_reason='manual').count()
    completed_other = attempts_qs.filter(status='completed').exclude(submission_reason='manual').count()
    timed_out = attempts_qs.filter(status='expired').count()

    finalized_total = completed_manual + completed_other + timed_out
    completion_rate = round((finalized_total / total_regs * 100), 1) if total_regs > 0 else 0.0

    # Activity signal logs
    total_activities = activities_qs.count()
    start_signals = activities_qs.filter(activity_type='ATTEMPT_STARTED').count()
    submit_signals = activities_qs.filter(activity_type='ATTEMPT_SUBMITTED').count()
    timeout_signals = activities_qs.filter(activity_type='ATTEMPT_TIMED_OUT').count()

    return {
        'total_registrations': total_regs,
        'active_registrations': active_regs.count(),
        'cancelled_registrations': cancelled_regs,
        'not_started': not_started,
        'in_progress': in_progress,
        'completed_manual': completed_manual,
        'completed_other': completed_other,
        'timed_out': timed_out,
        'finalized_total': finalized_total,
        'completion_rate': completion_rate,
        'total_activities': total_activities,
        'start_signals': start_signals,
        'submit_signals': submit_signals,
        'timeout_signals': timeout_signals,
    }


def get_candidate_cross_assessment_analytics(candidate_id):
    """
    Computes cross-assessment score comparisons, cumulative attempts, pass rate,
    performance trends over time, and topic-level strengths/weaknesses across all
    completed tests for a candidate.
    """
    candidate = Candidate.objects.filter(candidate_id=candidate_id).first()
    if not candidate:
        return None

    registrations = TestRegistration.objects.filter(
        candidate=candidate
    ).select_related('test').prefetch_related('attempt').order_by('registered_at')

    finalized_attempts = TestAttempt.objects.filter(
        registration__candidate=candidate,
        status__in=['completed', 'expired']
    ).select_related('registration__test').order_by('start_time')

    total_assigned = registrations.count()
    completed_count = finalized_attempts.count()
    passed_count = finalized_attempts.filter(is_passed=True).count()
    failed_count = finalized_attempts.filter(is_passed=False).count()
    pass_rate = round((passed_count / completed_count) * 100, 1) if completed_count > 0 else 0.0

    avg_pct_agg = finalized_attempts.aggregate(Avg('percentage'))['percentage__avg']
    avg_percentage = round(avg_pct_agg, 1) if avg_pct_agg is not None else 0.0

    # Cross-assessment comparison items & trend
    assessment_history = []
    trend_labels = []
    trend_percentages = []
    for att in finalized_attempts:
        test = att.registration.test
        sec = att.time_taken_seconds or 0
        m, s = divmod(sec, 60)
        time_str = f"{m}m {s}s" if m > 0 else f"{s}s"
        assessment_history.append({
            'attempt_id': str(att.attempt_id),
            'test_id': str(test.test_id),
            'test_name': test.test_name,
            'completed_date': att.end_time or att.start_time,
            'score': att.score,
            'total_questions': att.total_questions,
            'percentage': float(att.percentage or Decimal('0.00')),
            'is_passed': att.is_passed,
            'time_taken_formatted': time_str,
            'status': att.status,
        })
        trend_labels.append(test.test_name[:15])
        trend_percentages.append(float(att.percentage or Decimal('0.00')))

    # Aggregate topic strengths & weaknesses across all attempts
    aq_qs = AttemptQuestion.objects.filter(
        attempt__in=finalized_attempts
    ).select_related('question')

    topic_stats = {}
    for aq in aq_qs:
        t_name = aq.question.topic or 'General'
        if t_name not in topic_stats:
            topic_stats[t_name] = {'topic': t_name, 'correct': 0, 'total': 0}
        topic_stats[t_name]['total'] += 1
        if aq.is_correct:
            topic_stats[t_name]['correct'] += 1

    topic_strengths = []
    topic_weaknesses = []
    for t_data in topic_stats.values():
        acc = round((t_data['correct'] / t_data['total']) * 100, 1) if t_data['total'] > 0 else 0.0
        item = {'topic': t_data['topic'], 'accuracy': acc, 'total': t_data['total']}
        if acc >= 75.0:
            topic_strengths.append(item)
        elif acc < 50.0:
            topic_weaknesses.append(item)

    topic_strengths.sort(key=lambda x: -x['accuracy'])
    topic_weaknesses.sort(key=lambda x: x['accuracy'])

    return {
        'candidate': candidate,
        'total_assigned': total_assigned,
        'completed_count': completed_count,
        'passed_count': passed_count,
        'failed_count': failed_count,
        'pass_rate': pass_rate,
        'avg_percentage': avg_percentage,
        'assessment_history': assessment_history,
        'trend_labels': trend_labels,
        'trend_percentages': trend_percentages,
        'topic_strengths': topic_strengths,
        'topic_weaknesses': topic_weaknesses,
    }
