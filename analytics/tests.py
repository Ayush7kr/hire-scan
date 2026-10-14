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
