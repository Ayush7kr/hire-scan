"""
Comprehensive Automated Test Suite for Phase 4: Analytics and Reporting.

Covers:
1. Executive dashboard KPI calculations & empty state handling.
2. Filter application (test, status, date range).
3. Test summary analytics & metrics denominators.
4. Candidate performance rankings and percentile calculation formulas.
5. Question accuracy denominator enforcement (assigned occurrences only).
6. Topic-wise competency aggregation and improvement suggestions.
7. Completion pipeline mutually exclusive categorization.
8. Official PDF scorecard export and answer key isolation.
9. Batch CSV exports with Spreadsheet Formula Injection (CSV Injection) protection.
10. Authorization, IDOR protection, and regression validation.
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration
from attempts.models import TestAttempt, AttemptQuestion
from attempts.services import (
    start_attempt_for_registration,
    evaluate_attempt,
)
from analytics.services import (
    sanitize_csv_cell,
    calculate_candidate_rankings_and_percentiles,
    get_dashboard_analytics,
    get_test_summary_analytics,
    get_question_analysis_analytics,
    get_topic_analytics,
    get_completion_analytics,
    get_candidate_cross_assessment_analytics,
)


class AnalyticsBaseTestCase(TestCase):
    """Base setup for analytics tests with test banks, multiple candidates, and evaluated attempts."""

    def setUp(self):
        # Admin User
        self.admin = Admin(
            name="Analytics Administrator",
            email="analytics.admin@hirescan.local"
        )
        self.admin.set_password("AdminSecure2026!")
        self.admin.save()

        # Candidates (4 candidates to create diverse cohort)
        self.cand1 = Candidate.objects.create(name="Alice Walker", email="alice@test.local", is_active=True)
        self.cand2 = Candidate.objects.create(name="Bob Smith", email="bob@test.local", is_active=True)
        self.cand3 = Candidate.objects.create(name="Charlie Davis", email="charlie@test.local", is_active=True)
        self.cand4 = Candidate.objects.create(name="Dana Evans", email="dana@test.local", is_active=True)

        # Assessment 1: Python Architecture (5 questions, pass: 3)
        self.test1 = Test.objects.create(
            test_name="Python Backend Mastery",
            description="Core Django & Python architectures.",
            duration_minutes=30,
            total_questions=5,
            passing_marks=3,
            is_active=True
        )

        # Assessment 2: Data Structures (4 questions, pass: 2)
        self.test2 = Test.objects.create(
            test_name="Algorithms & Data Structures",
            description="Algorithmic problem solving.",
            duration_minutes=25,
            total_questions=4,
            passing_marks=2,
            is_active=True
        )

        # Create question bank for Test 1 (6 questions across 2 topics)
        self.t1_questions = []
        for i in range(1, 7):
            topic = "Python Internals" if i <= 3 else "Database Optimization"
            q = Question.objects.create(
                test=self.test1,
                question_text=f"Test 1 Question {i}: Performance and architecture topic {i}",
                option1=f"T1 Option 1 for Q{i}",
                option2=f"T1 Option 2 for Q{i}",
                option3=f"T1 Option 3 for Q{i}",
                option4=f"T1 Option 4 for Q{i}",
                correct_option=1,  # Option 1 is always correct
                topic=topic,
                difficulty="medium",
                suggestions=f"Review concepts in {topic}."
            )
            self.t1_questions.append(q)

        # Create question bank for Test 2 (5 questions)
        self.t2_questions = []
        for i in range(1, 6):
            q = Question.objects.create(
                test=self.test2,
                question_text=f"Test 2 Question {i}: Algorithmic complexity {i}",
                option1=f"T2 Option 1 for Q{i}",
                option2=f"T2 Option 2 for Q{i}",
                option3=f"T2 Option 3 for Q{i}",
                option4=f"T2 Option 4 for Q{i}",
                correct_option=2,  # Option 2 is always correct
                topic="Algorithms",
                difficulty="hard",
                suggestions="Review algorithmic time complexities."
            )
            self.t2_questions.append(q)

        # Registrations for Test 1
        self.reg1 = TestRegistration.objects.create(candidate=self.cand1, test=self.test1, status='registered')
        self.reg2 = TestRegistration.objects.create(candidate=self.cand2, test=self.test1, status='registered')
        self.reg3 = TestRegistration.objects.create(candidate=self.cand3, test=self.test1, status='registered')
        self.reg4 = TestRegistration.objects.create(candidate=self.cand4, test=self.test1, status='registered')

        # Attempts for Test 1:
        # 1) Alice: score 5/5 (Passed)
        self.att1 = start_attempt_for_registration(self.reg1)
        for aq in self.att1.attempt_questions.all():
            aq.selected_option = aq.question.correct_option
            aq.save()
        evaluate_attempt(self.att1, submission_reason='manual')

        # 2) Bob: score 3/5 (Passed boundary)
        self.att2 = start_attempt_for_registration(self.reg2)
        aqs2 = list(self.att2.attempt_questions.all())
        for aq in aqs2[:3]:
            aq.selected_option = aq.question.correct_option
            aq.save()
        for aq in aqs2[3:]:
            aq.selected_option = 4  # incorrect
            aq.save()
        evaluate_attempt(self.att2, submission_reason='manual')

        # 3) Charlie: score 1/5 (Failed, Timed Out)
        self.att3 = start_attempt_for_registration(self.reg3)
        aqs3 = list(self.att3.attempt_questions.all())
        aqs3[0].selected_option = aqs3[0].question.correct_option
        aqs3[0].save()
        evaluate_attempt(self.att3, submission_reason='timeout')

        # 4) Dana: Registration created, but NOT started (idle)

        # HTTP Clients
        self.admin_client = Client()
        s_adm = self.admin_client.session
        s_adm['admin_id'] = str(self.admin.admin_id)
        s_adm.save()

        self.alice_client = Client()
        s_a = self.alice_client.session
        s_a['candidate_id'] = str(self.cand1.candidate_id)
        s_a.save()

        self.bob_client = Client()
        s_b = self.bob_client.session
        s_b['candidate_id'] = str(self.cand2.candidate_id)
        s_b.save()

        self.anon_client = Client()


class AnalyticsDashboardTests(AnalyticsBaseTestCase):
    """Tests for dashboard calculations, filter handling, and empty dataset safety."""

    def test_dashboard_metrics_calculation(self):
        """Dashboard KPIs accurately reflect database records and denominators."""
        analytics = get_dashboard_analytics()

        self.assertEqual(analytics['total_tests'], 2)
        self.assertEqual(analytics['active_tests'], 2)
        self.assertEqual(analytics['total_registrations'], 4)
        self.assertEqual(analytics['total_attempts_started'], 3)
        self.assertEqual(analytics['finalized_count'], 3)
        self.assertEqual(analytics['completed_count'], 2)
        self.assertEqual(analytics['expired_count'], 1)
        self.assertEqual(analytics['passed_count'], 2)  # Alice (5/5) & Bob (3/5)
        self.assertEqual(analytics['failed_count'], 1)  # Charlie (1/5)

        # Pass Rate = 2 passed / 3 finalized = 66.7%
        self.assertEqual(analytics['overall_pass_rate'], 66.7)

        # Average Score = (5 + 3 + 1) / 3 = 3.0 pts
        self.assertEqual(analytics['avg_score'], 3.0)

        # Average Percentage = (100 + 60 + 20) / 3 = 60.0%
        self.assertEqual(analytics['avg_percentage'], 60.0)

        # Completion Rate = 3 finalized / 4 registrations = 75.0%
        self.assertEqual(analytics['completion_rate'], 75.0)

    def test_dashboard_view_renders_200_for_admin(self):
        """Admin dashboard page is accessible and displays real calculated metrics."""
        res = self.admin_client.get(reverse('admin_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Executive Analytics Dashboard")
        self.assertContains(res, "66.7%")  # Pass rate
        self.assertContains(res, "Python Backend Mastery")

    def test_dashboard_handles_empty_dataset_gracefully(self):
        """Empty database handles all calculations without division-by-zero or crashes."""
        TestRegistration.objects.all().delete()
        TestAttempt.objects.all().delete()
        Test.objects.all().delete()

        analytics = get_dashboard_analytics()
        self.assertEqual(analytics['total_tests'], 0)
        self.assertEqual(analytics['overall_pass_rate'], 0.0)
        self.assertEqual(analytics['avg_score'], 0.0)
        self.assertEqual(analytics['completion_rate'], 0.0)

        res = self.admin_client.get(reverse('admin_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "0.0%")

    def test_dashboard_filtering_by_test_and_status(self):
        """Filters by test_id and status isolate corresponding attempts."""
        # Filter for Test 1 with status 'expired' (Charlie only)
        filters = {
            'test_id': str(self.test1.test_id),
            'status': 'expired'
        }
        analytics = get_dashboard_analytics(filters)
        self.assertEqual(analytics['finalized_count'], 1)
        self.assertEqual(analytics['passed_count'], 0)
        self.assertEqual(analytics['failed_count'], 1)
        self.assertEqual(analytics['overall_pass_rate'], 0.0)
        self.assertEqual(analytics['avg_score'], 1.0)


class CandidateRankingAndPercentileTests(AnalyticsBaseTestCase):
    """Tests for relative ranking, tie-breaking, and psychometric percentile formula."""

    def test_ranking_and_percentile_formula(self):
        """
        In Test 1 with 3 finalized attempts:
          - Alice: Score 5 -> 0 below, 1 equal (self) -> B=2 lower?
            Wait: all_scores = [5, 3, 1]
            Alice (5): B=2 (3 and 1 are lower), E=1. Percentile = (2 + 0.5*1)/3 * 100 = 83.3%
            Bob (3): B=1 (1 is lower), E=1. Percentile = (1 + 0.5*1)/3 * 100 = 50.0%
            Charlie (1): B=0, E=1. Percentile = (0 + 0.5*1)/3 * 100 = 16.7%
        """
        rankings = calculate_candidate_rankings_and_percentiles(self.test1.test_id)
        self.assertEqual(len(rankings), 3)

        alice_rank = rankings[str(self.att1.attempt_id)]
        self.assertEqual(alice_rank['rank'], 1)
        self.assertEqual(alice_rank['percentile'], 83.3)

        bob_rank = rankings[str(self.att2.attempt_id)]
        self.assertEqual(bob_rank['rank'], 2)
        self.assertEqual(bob_rank['percentile'], 50.0)

        charlie_rank = rankings[str(self.att3.attempt_id)]
        self.assertEqual(charlie_rank['rank'], 3)
        self.assertEqual(charlie_rank['percentile'], 16.7)

    def test_ranking_tie_handling(self):
        """When two candidates have the same score, they share equal ranking and symmetric percentile."""
        # Create candidate 5 with score 3 (same as Bob)
        cand5 = Candidate.objects.create(name="Eve Tie", email="eve@test.local")
        reg5 = TestRegistration.objects.create(candidate=cand5, test=self.test1, status='registered')
        att5 = start_attempt_for_registration(reg5)
        aqs5 = list(att5.attempt_questions.all())
        for aq in aqs5[:3]:
            aq.selected_option = aq.question.correct_option
            aq.save()
        evaluate_attempt(att5, submission_reason='manual')

        # Now cohort has 4 candidates: scores [5, 3, 3, 1]
        rankings = calculate_candidate_rankings_and_percentiles(self.test1.test_id)
        self.assertEqual(len(rankings), 4)

        # Both Bob and Eve tied for 2nd rank
        bob_r = rankings[str(self.att2.attempt_id)]
        eve_r = rankings[str(att5.attempt_id)]

        self.assertEqual(bob_r['rank'], 2)
        self.assertEqual(eve_r['rank'], 2)
        # For score 3: B=1 (score 1 is lower), E=2 (Bob & Eve).
        # Percentile = (1 + 0.5 * 2) / 4 * 100 = 50.0%
        self.assertEqual(bob_r['percentile'], 50.0)
        self.assertEqual(eve_r['percentile'], 50.0)

    def test_single_candidate_percentile_returns_unavailable(self):
        """
        When only one candidate has finalized an assessment (N=1), psychometric percentile
        cannot be meaningfully calculated relative to a cohort.
        Rank must be 1, and percentile must be '—' (unavailable state).
        """
        # Create a new test with only 1 candidate and attempt
        single_test = Test.objects.create(
            test_name="Single Examinee Test",
            duration_minutes=30,
            total_questions=1,
            passing_marks=1,
            is_active=True
        )
        q = Question.objects.create(
            test=single_test,
            question_text="Sample Q",
            option1="A",
            option2="B",
            option3="C",
            option4="D",
            correct_option=1,
            topic="General"
        )
        cand = Candidate.objects.create(name="Lone Candidate", email="lone@test.local")
        reg = TestRegistration.objects.create(candidate=cand, test=single_test, status='registered')
        att = start_attempt_for_registration(reg)
        aq = att.attempt_questions.first()
        aq.selected_option = 1
        aq.save()
        evaluate_attempt(att, submission_reason='manual')

        rankings = calculate_candidate_rankings_and_percentiles(single_test.test_id)
        self.assertEqual(len(rankings), 1)
        lone_rank = rankings[str(att.attempt_id)]
        self.assertEqual(lone_rank['rank'], 1)
        self.assertEqual(lone_rank['percentile'], '—')

    def test_zero_finalized_candidates_ranking(self):
        """When an assessment has no finalized attempts, rankings dictionary is empty."""
        empty_test = Test.objects.create(
            test_name="Empty Test",
            duration_minutes=30,
            total_questions=1,
            passing_marks=1,
            is_active=True
        )
        rankings = calculate_candidate_rankings_and_percentiles(empty_test.test_id)
        self.assertEqual(rankings, {})



class QuestionAndTopicAnalysisTests(AnalyticsBaseTestCase):
    """Tests for question accuracy denominators and topic aggregation."""

    def test_question_accuracy_denominator_uses_assigned_attempts_only(self):
        """
        Question accuracy denominator MUST be the number of times the question was
        assigned in finalized attempts, NOT the total registered candidate count.
        """
        analysis = get_question_analysis_analytics(self.test1.test_id)
        self.assertTrue(len(analysis) > 0)

        for q_item in analysis:
            # assigned_count must be <= 3 (since only 3 finalized attempts exist)
            self.assertLessEqual(q_item['assigned_count'], 3)
            if q_item['assigned_count'] > 0:
                expected_acc = round((q_item['correct_count'] / q_item['assigned_count']) * 100, 1)
                self.assertEqual(q_item['accuracy'], expected_acc)

    def test_topic_analytics_aggregation(self):
        """Topic breakdown aggregates accuracies and suggestions across topics."""
        topic_data = get_topic_analytics(self.test1.test_id)
        topic_names = [t['topic'] for t in topic_data]

        self.assertIn("Python Internals", topic_names)
        self.assertIn("Database Optimization", topic_names)

        for t in topic_data:
            self.assertIn(t['level'], ['Proficient', 'Average', 'Needs Work', 'No Data'])
            if t['assigned_count'] > 0:
                self.assertEqual(
                    t['accuracy'],
                    round((t['correct_count'] / t['assigned_count']) * 100, 1)
                )


class CompletionPipelineTests(AnalyticsBaseTestCase):
    """Tests for mutually exclusive pipeline status categorization."""

    def test_pipeline_categories_are_mutually_exclusive(self):
        """
        Candidates in the pipeline must fall into mutually exclusive categories:
        - Total registrations = 4
        - Finalized total = 3 (Alice=manual, Bob=manual, Charlie=timeout)
        - Not started = 1 (Dana)
        - In progress = 0
        """
        completion = get_completion_analytics(self.test1.test_id)

        self.assertEqual(completion['total_registrations'], 4)
        self.assertEqual(completion['not_started'], 1)
        self.assertEqual(completion['completed_manual'], 2)
        self.assertEqual(completion['timed_out'], 1)
        self.assertEqual(completion['in_progress'], 0)
        self.assertEqual(completion['finalized_total'], 3)
        self.assertEqual(completion['completion_rate'], 75.0)


class PDFExportTests(AnalyticsBaseTestCase):
    """Tests for candidate scorecard PDF generation and answer key isolation."""

    def test_candidate_can_download_their_own_pdf_scorecard(self):
        """Alice can download her own PDF scorecard with valid PDF headers."""
        res = self.alice_client.get(reverse('attempt_scorecard_pdf', args=[self.att1.attempt_id]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('attachment', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF-'))

    def test_administrator_can_download_candidate_pdf_scorecard(self):
        """Administrator can download examinee scorecard PDF."""
        res = self.admin_client.get(reverse('attempt_scorecard_pdf', args=[self.att1.attempt_id]))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b'%PDF-'))

    def test_candidate_cannot_download_another_candidate_pdf(self):
        """Bob is denied (403 Forbidden) when requesting Alice's PDF scorecard."""
        res = self.bob_client.get(reverse('attempt_scorecard_pdf', args=[self.att1.attempt_id]))
        self.assertEqual(res.status_code, 403)

    def test_pdf_does_not_reveal_correct_answers_to_candidate(self):
        """PDF generation does not leak Question.correct_option text."""
        res = self.alice_client.get(reverse('attempt_scorecard_pdf', args=[self.att1.attempt_id]))
        # Binary PDF content should not contain explicit answer key headers
        self.assertNotIn(b"Correct Key", res.content)


class BatchCSVExportTests(AnalyticsBaseTestCase):
    """Tests for batch CSV exports and formula injection sanitization."""

    def test_formula_injection_sanitization(self):
        """Dangerous leading formula characters (=, +, -, @, \\t, \\r) are sanitized with ' prefix."""
        self.assertEqual(sanitize_csv_cell("=SUM(1,2)"), "'=SUM(1,2)")
        self.assertEqual(sanitize_csv_cell("+cmd|' /C calc'!A0"), "'+cmd|' /C calc'!A0")
        self.assertEqual(sanitize_csv_cell("-123"), "'-123")
        self.assertEqual(sanitize_csv_cell("@alert"), "'@alert")
        self.assertEqual(sanitize_csv_cell("Safe Content"), "Safe Content")
        self.assertEqual(sanitize_csv_cell(None), "")

    def test_export_test_summary_csv(self):
        """Exporting test summary produces valid CSV content with UTF-8 BOM."""
        res = self.admin_client.get(reverse('analytics_export_tests'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res['Content-Type'])
        content = res.content.decode('utf-8-sig')
        self.assertIn('Test Name', content)
        self.assertIn('Python Backend Mastery', content)

    def test_export_candidate_performance_csv(self):
        """Exporting candidate performance CSV includes cohort ranks and percentages."""
        res = self.admin_client.get(reverse('analytics_export_candidates') + f"?test_id={self.test1.test_id}")
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8-sig')
        self.assertIn('Alice Walker', content)
        self.assertIn('Bob Smith', content)
        self.assertIn('Cohort Rank', content)
        self.assertIn('Cohort Percentile', content)

    def test_export_questions_csv(self):
        """Question analysis CSV includes correct columns and accuracy values."""
        res = self.admin_client.get(reverse('analytics_export_questions') + f"?test_id={self.test1.test_id}")
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8-sig')
        self.assertIn('Question ID', content)
        self.assertIn('Accuracy Rate (%)', content)

    def test_export_topics_csv(self):
        """Topic CSV export contains topic breakdown and recommendations."""
        res = self.admin_client.get(reverse('analytics_export_topics') + f"?test_id={self.test1.test_id}")
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8-sig')
        self.assertIn('Python Internals', content)
        self.assertIn('Accuracy Rate (%)', content)

    def test_unauthorized_user_cannot_export_csv(self):
        """Unauthenticated requests to CSV exports redirect to admin login."""
        res = self.anon_client.get(reverse('analytics_export_candidates'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('admin_login'), res.url)


class ReportViewsAuthorizationTests(AnalyticsBaseTestCase):
    """Tests for role-based authorization across all analytical report views."""

    def test_all_analytics_views_require_admin_authentication(self):
        """Unauthenticated requests to any analytical view are redirected to login."""
        routes = [
            reverse('analytics_test_summary'),
            reverse('analytics_test_detail', args=[self.test1.test_id]),
            reverse('analytics_candidate_performance'),
            reverse('analytics_question_analysis'),
            reverse('analytics_topic_performance'),
            reverse('analytics_completion_report'),
        ]
        for url in routes:
            res = self.anon_client.get(url)
            self.assertEqual(res.status_code, 302, f"Failed for URL: {url}")
            self.assertIn(reverse('admin_login'), res.url)

    def test_admin_can_access_all_report_views(self):
        """Authenticated administrator can access all reporting pages."""
        routes = [
            reverse('analytics_test_summary'),
            reverse('analytics_test_detail', args=[self.test1.test_id]),
            reverse('analytics_candidate_performance'),
            reverse('analytics_question_analysis'),
            reverse('analytics_topic_performance'),
            reverse('analytics_completion_report'),
        ]
        for url in routes:
            res = self.admin_client.get(url)
            self.assertEqual(res.status_code, 200, f"Failed for URL: {url}")


class AdminUINavigationAndFilteringTests(AnalyticsBaseTestCase):
    """
    Tests for Admin UI consistency, sidebar completeness, candidate performance filtering,
    server-side pagination, contextual attempt navigation, and dashboard audit stream.
    """

    def test_candidate_import_sidebar_contains_all_11_links_and_active_state(self):
        """Candidate Imports page must render the full shared sidebar including Analytics & Reports."""
        res = self.admin_client.get(reverse('candidate_import'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Check all 11 core admin links exist in sidebar
        expected_links = [
            reverse('admin_dashboard'),
            reverse('candidate_list'),
            reverse('candidate_import'),
            reverse('test_list'),
            reverse('registration_list'),
            reverse('analytics_test_summary'),
            reverse('analytics_candidate_performance'),
            reverse('analytics_question_analysis'),
            reverse('analytics_topic_performance'),
            reverse('analytics_completion_report'),
            reverse('admin_logout'),
        ]
        for link in expected_links:
            self.assertIn(link, content, f"Expected sidebar link {link} missing on candidate_import")

        # Verify active class on candidate_import
        self.assertIn('Candidate Imports', content)
        self.assertIn('Analytics & Reports', content)

    def test_candidate_performance_search_and_filters(self):
        """Candidate Performance report filters by name/email, test, status, and outcome."""
        url = reverse('analytics_candidate_performance')

        # Search by partial candidate name
        res_name = self.admin_client.get(url, {'q': 'Alice'})
        self.assertEqual(res_name.status_code, 200)
        self.assertIn('Alice Walker', res_name.content.decode('utf-8'))
        self.assertNotIn('Bob Smith', res_name.content.decode('utf-8'))

        # Search by partial email
        res_email = self.admin_client.get(url, {'q': 'bob@test'})
        self.assertEqual(res_email.status_code, 200)
        self.assertIn('Bob Smith', res_email.content.decode('utf-8'))
        self.assertNotIn('Alice Walker', res_email.content.decode('utf-8'))

        # Filter by test_id
        res_test = self.admin_client.get(url, {'test_id': str(self.test1.test_id)})
        self.assertEqual(res_test.status_code, 200)
        self.assertEqual(res_test.context['total_count'], 3)

        # Filter by outcome passed
        res_passed = self.admin_client.get(url, {'outcome': 'passed'})
        self.assertEqual(res_passed.status_code, 200)
        # Alice passed (5/5 >= 60%), Bob passed (3/5 = 60%), Charlie failed (1/5 = 20%)
        self.assertIn('Alice Walker', res_passed.content.decode('utf-8'))
        self.assertNotIn('Charlie Davis', res_passed.content.decode('utf-8'))

        # Filter by outcome failed
        res_failed = self.admin_client.get(url, {'outcome': 'failed'})
        self.assertEqual(res_failed.status_code, 200)
        self.assertIn('Charlie Davis', res_failed.content.decode('utf-8'))
        self.assertNotIn('Alice Walker', res_failed.content.decode('utf-8'))

        # Combined filters: Alice, passed, completed
        res_comb = self.admin_client.get(url, {'q': 'Alice', 'outcome': 'passed', 'status': 'completed'})
        self.assertEqual(res_comb.status_code, 200)
        self.assertIn('Alice Walker', res_comb.content.decode('utf-8'))
        self.assertEqual(res_comb.context['total_count'], 1)

    def test_candidate_performance_query_string_preservation(self):
        """Candidate performance view computes filter_querystring cleanly without page."""
        url = reverse('analytics_candidate_performance')
        res = self.admin_client.get(url, {'q': 'Alice', 'outcome': 'passed', 'page': '1'})
        self.assertEqual(res.status_code, 200)
        f_qs = res.context['filter_querystring']
        self.assertIn('q=Alice', f_qs)
        self.assertIn('outcome=passed', f_qs)
        self.assertNotIn('page=', f_qs)

    def test_attempt_detail_contextual_navigation_from_candidate_performance(self):
        """Clicking View Attempt from Candidate Performance passes navigation context and back link."""
        url = reverse('admin_attempt_detail', args=[self.att1.attempt_id]) + '?from=candidate_performance&q=Alice'
        res = self.admin_client.get(url)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Contextual breadcrumb and Back button
        self.assertIn('Candidate Performance', content)
        self.assertIn('Back to Candidate Performance', content)
        self.assertIn('q=Alice', content)

    def test_standard_attempt_inspection_from_tests_workflow_preserved(self):
        """Navigating to attempt detail from Tests workflow displays Tests breadcrumbs and Back to Attempts."""
        url = reverse('admin_attempt_detail', args=[self.att1.attempt_id])
        res = self.admin_client.get(url)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        self.assertIn('Back to Attempts List', content)

    def test_dashboard_audit_stream_has_scrollable_container(self):
        """Dashboard renders Audit Activity Stream inside scrollable container."""
        res = self.admin_client.get(reverse('admin_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('audit-activity-container', res.content.decode('utf-8'))


class AdvancedAnalyticsAndAutomatedReportTests(AnalyticsBaseTestCase):
    """
    Automated regression and functional tests for Phase C:
    - Feature 4: Advanced Assessment Analytics (median, std dev, score brackets,
      facility/discrimination psychometrics, cross-assessment candidate profiles).
    - Feature 6: Automated Report Generation (ReportLab PDF exports for test summaries
      and filtered candidate results with 2-line security footers).
    """

    def test_advanced_summary_metrics_median_std_dev_and_buckets(self):
        """Advanced test metrics include median, std_dev, score range, and score distribution buckets."""
        summary = get_test_summary_analytics(self.test1.test_id)

        # 3 attempts with scores: Alice=5, Bob=3, Charlie=1
        self.assertEqual(summary['median_score'], 3.0)
        self.assertEqual(summary['score_range'], 4.0)
        self.assertGreater(summary['std_dev_score'], 0)

        # Distribution buckets
        buckets = summary['distribution_buckets']
        # Charlie is 20% (1/5) -> Below Standard (<50%)
        b_below_50 = next(b for b in buckets if 'Below Standard' in b['label'])
        self.assertEqual(b_below_50['count'], 1)
        self.assertEqual(b_below_50['pct'], 33.3)

        # Bob is 60% (3/5) -> Average (50-74%)
        b_avg = next(b for b in buckets if 'Average' in b['label'])
        self.assertEqual(b_avg['count'], 1)

        # Alice is 100% (5/5) -> Excellent (90-100%)
        b_exc = next(b for b in buckets if 'Excellent' in b['label'])
        self.assertEqual(b_exc['count'], 1)

    def test_question_analysis_facility_and_discrimination_indices(self):
        """Question analysis computes item facility index and discrimination index."""
        # Initial analysis with 3 attempts
        analysis = get_question_analysis_analytics(self.test1.test_id)
        self.assertTrue(len(analysis) > 0)
        q1_data = analysis[0]
        self.assertIsNotNone(q1_data['facility_index'])

        # Create a 4th attempt for Dana to achieve cohort >= 4
        self.att4 = start_attempt_for_registration(self.reg4)
        for aq in self.att4.attempt_questions.all():
            aq.selected_option = 3  # incorrect
            aq.save()
        evaluate_attempt(self.att4, submission_reason='manual')

        # Ensure target question is deterministically present across all 4 finalized attempts
        target_q = self.t1_questions[0]
        for att in [self.att1, self.att2, self.att3, self.att4]:
            aq, _ = AttemptQuestion.objects.get_or_create(
                attempt=att,
                question=target_q,
                defaults={'selected_option': 3, 'is_correct': False, 'question_order': 99}
            )
            aq.is_correct = (aq.selected_option == target_q.correct_option)
            aq.save()

        analysis_cohort4 = get_question_analysis_analytics(self.test1.test_id)
        # With cohort >= 4 on target_q, discrimination index is numerically calculated
        q1_data_cohort4 = next(q for q in analysis_cohort4 if q['question'].question_id == target_q.question_id)
        self.assertIsNotNone(q1_data_cohort4['discrimination_index'])
        self.assertNotEqual(q1_data_cohort4['discrimination_display'], "— (Cohort < 4)")

    def test_candidate_cross_assessment_analytics_with_multiple_assessments(self):
        """Candidate cross-assessment analytics tracks performance across multiple assessments."""
        # Alice already took test1 (score 5/5, 100%, passed)
        # Register Alice for test2
        reg_t2 = TestRegistration.objects.create(candidate=self.cand1, test=self.test2, status='registered')
        att_t2 = start_attempt_for_registration(reg_t2)
        aqs = list(att_t2.attempt_questions.all())
        # Correctly answer 2 of 4 questions for test 2
        for aq in aqs[:2]:
            aq.selected_option = aq.question.correct_option
            aq.save()
        for aq in aqs[2:]:
            aq.selected_option = 1  # incorrect (correct is 2)
            aq.save()
        evaluate_attempt(att_t2, submission_reason='manual')

        cross_data = get_candidate_cross_assessment_analytics(self.cand1.candidate_id)
        self.assertIsNotNone(cross_data)
        self.assertEqual(cross_data['total_assigned'], 2)
        self.assertEqual(cross_data['completed_count'], 2)
        self.assertEqual(cross_data['passed_count'], 2)
        self.assertEqual(cross_data['failed_count'], 0)
        self.assertEqual(cross_data['pass_rate'], 100.0)
        # (100% + 50%) / 2 = 75.0%
        self.assertEqual(cross_data['avg_percentage'], 75.0)
        self.assertEqual(len(cross_data['assessment_history']), 2)
        self.assertEqual(cross_data['trend_percentages'], [100.0, 50.0])

    def test_candidate_cross_assessment_analytics_empty_state_safety(self):
        """Candidate with zero completed attempts returns graceful zero-metrics without DivisionByZero."""
        # Dana has a registration but no finalized attempts
        cross_data = get_candidate_cross_assessment_analytics(self.cand4.candidate_id)
        self.assertIsNotNone(cross_data)
        self.assertEqual(cross_data['completed_count'], 0)
        self.assertEqual(cross_data['pass_rate'], 0.0)
        self.assertEqual(cross_data['avg_percentage'], 0.0)
        self.assertEqual(cross_data['assessment_history'], [])
        self.assertEqual(cross_data['topic_strengths'], [])
        self.assertEqual(cross_data['topic_weaknesses'], [])

    def test_export_test_summary_pdf_admin_authorized(self):
        """Admin can export Assessment Summary PDF containing ReportLab binary content."""
        url = reverse('analytics_export_test_pdf', args=[self.test1.test_id])
        res = self.admin_client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', res['Content-Disposition'])
        self.assertIn('HireScan_Assessment_Summary_', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF'))

        # Verifies activity log was recorded
        log = ActivityLog.objects.filter(activity_type='report_exported_pdf').first()
        self.assertIsNotNone(log)
        self.assertIn(self.test1.test_name, log.activity_details)

    def test_export_test_summary_pdf_security_and_idor(self):
        """Non-admin requests are redirected/blocked, non-existent tests return 404."""
        url = reverse('analytics_export_test_pdf', args=[self.test1.test_id])

        # Candidate cannot export assessment summary
        res_cand = self.alice_client.get(url)
        self.assertEqual(res_cand.status_code, 302)

        # Anonymous cannot export
        res_anon = self.anon_client.get(url)
        self.assertEqual(res_anon.status_code, 302)

        # 404 for invalid test ID
        res_404 = self.admin_client.get(reverse('analytics_export_test_pdf', args=[uuid.uuid4()]))
        self.assertEqual(res_404.status_code, 404)

    def test_export_candidate_results_pdf_admin_authorized_and_filtered(self):
        """Admin can export filter-scoped Candidate Results PDF."""
        url = reverse('analytics_export_candidates_pdf')
        res = self.admin_client.get(url, {'test_id': str(self.test1.test_id), 'outcome': 'passed'})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', res['Content-Disposition'])
        self.assertTrue(res.content.startswith(b'%PDF'))

    def test_export_candidate_results_pdf_empty_dataset_safe(self):
        """Exporting Candidate Results PDF with a filter matching 0 candidates generates valid PDF without error."""
        url = reverse('analytics_export_candidates_pdf')
        res = self.admin_client.get(url, {'q': 'NonExistentCandidateNameXYZ999'})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertTrue(res.content.startswith(b'%PDF'))

    def test_candidate_detail_view_renders_cross_analytics_cards(self):
        """Candidate detail view displays cross-assessment performance, trends, and topic profiles."""
        url = reverse('candidate_detail', args=[self.cand1.candidate_id])
        res = self.admin_client.get(url)

        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Cross-Assessment Analytics', content)
        self.assertIn('Assessment Score History', content)
        self.assertIn('Demonstrated Topic Strengths', content)

    def test_test_summary_detail_renders_pdf_button_and_distribution(self):
        """Assessment summary detail page displays Download PDF Summary action and distribution cards."""
        url = reverse('analytics_test_detail', args=[self.test1.test_id])
        res = self.admin_client.get(url)

        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Download PDF Summary', content)
        self.assertIn('Score Distribution Breakdown', content)
        self.assertIn('Statistical Distribution', content)

    def test_candidate_performance_renders_export_pdf_button(self):
        """Candidate performance page renders Export Filtered PDF button."""
        url = reverse('analytics_candidate_performance')
        res = self.admin_client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertIn('Export Filtered PDF', res.content.decode('utf-8'))

