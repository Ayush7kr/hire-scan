"""
Automated Test Suite for Phase 3: Candidate Assessment Engine.

Covers:
- Assessment eligibility & attempt creation
- Randomized question sampling & stable ordering persistence
- Autosave API validation & persistence
- Server-authoritative timer & timeout finalization
- Idempotent manual & timeout submission
- Server-side scoring, evaluation, and topic performance
- Object-level authorization, anti-tampering, and IDOR protection
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
    validate_candidate_eligibility,
    start_attempt_for_registration,
    evaluate_attempt,
    get_topic_performance,
)


class AssessmentEngineBaseTestCase(TestCase):
    """Base setup for assessment engine tests with test bank and candidate fixtures."""

    def setUp(self):
        # Admin account
        self.admin = Admin(
            name="Assessment Auditor",
            email="auditor@hirescan.local"
        )
        self.admin.set_password("AdminSecure2026!")
        self.admin.save()

        # Candidates
        self.candidate1 = Candidate.objects.create(
            name="Candidate Alice",
            email="alice@exam.local",
            is_active=True
        )
        self.candidate2 = Candidate.objects.create(
            name="Candidate Bob",
            email="bob@exam.local",
            is_active=True
        )

        # Assessment: 5 questions required, 3 to pass, 30 mins
        self.test = Test.objects.create(
            test_name="Python & Architecture Fundamentals",
            description="Core technical evaluation.",
            duration_minutes=30,
            total_questions=5,
            passing_marks=3,
            is_active=True
        )

        # Create question bank of 8 questions (greater than total_questions=5)
        self.questions = []
        topics = ['Python Basics', 'Algorithms', 'Databases', 'Web Standards']
        for i in range(1, 9):
            topic = topics[(i - 1) % len(topics)]
            q = Question.objects.create(
                test=self.test,
                question_text=f"Question {i}: What is the expected behavior of test case {i}?",
                option1=f"Option 1 for Q{i}",
                option2=f"Option 2 for Q{i}",
                option3=f"Option 3 for Q{i}",
                option4=f"Option 4 for Q{i}",
                correct_option=(i % 4) + 1,  # Deterministic correct option 1..4
                topic=topic,
                difficulty='medium',
                suggestions=f"Study {topic} guidelines."
            )
            self.questions.append(q)

        # Registration for Candidate 1
        self.registration = TestRegistration.objects.create(
            candidate=self.candidate1,
            test=self.test,
            status='registered'
        )

        # HTTP Clients
        self.alice_client = Client()
        s1 = self.alice_client.session
        s1['candidate_id'] = str(self.candidate1.candidate_id)
        s1.save()

        self.bob_client = Client()
        s2 = self.bob_client.session
        s2['candidate_id'] = str(self.candidate2.candidate_id)
        s2.save()

        self.admin_client = Client()
        sa = self.admin_client.session
        sa['admin_id'] = str(self.admin.admin_id)
        sa.save()

        self.anon_client = Client()


class AttemptCreationTests(AssessmentEngineBaseTestCase):
    """Tests for eligibility checks, transactional attempt creation, and question sampling."""

    def test_eligible_candidate_can_view_instructions_and_start_test(self):
        """Candidate with valid registration can view instructions and start test via POST."""
        res_instr = self.alice_client.get(
            reverse('test_instructions', args=[self.registration.registration_id])
        )
        self.assertEqual(res_instr.status_code, 200)
        self.assertContains(res_instr, "Python")
        self.assertContains(res_instr, "Architecture Fundamentals")
        self.assertContains(res_instr, "30 minutes")


        # Starting test creates attempt and redirects to test_take
        res_start = self.alice_client.post(
            reverse('test_start', args=[self.registration.registration_id])
        )
        attempt = TestAttempt.objects.filter(registration=self.registration).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status, 'in_progress')
        self.assertEqual(attempt.total_questions, 5)
        self.assertRedirects(res_start, reverse('test_take', args=[attempt.attempt_id]))

    def test_unregistered_candidate_is_denied(self):
        """Candidate cannot start a test they are not registered for."""
        res = self.bob_client.get(
            reverse('test_instructions', args=[self.registration.registration_id])
        )
        self.assertEqual(res.status_code, 403)

        res_post = self.bob_client.post(
            reverse('test_start', args=[self.registration.registration_id])
        )
        self.assertEqual(res_post.status_code, 403)

    def test_inactive_test_is_denied(self):
        """Inactive test cannot be started."""
        self.test.is_active = False
        self.test.save()

        res = self.alice_client.get(
            reverse('test_instructions', args=[self.registration.registration_id])
        )
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('candidate_dashboard'))

        res_start = self.alice_client.post(
            reverse('test_start', args=[self.registration.registration_id])
        )
        self.assertEqual(res_start.status_code, 302)
        self.assertFalse(TestAttempt.objects.filter(registration=self.registration).exists())

    def test_inactive_candidate_is_denied(self):
        """Deactivated candidate is rejected by eligibility check."""
        self.candidate1.is_active = False
        self.candidate1.save()

        is_eligible, reason = validate_candidate_eligibility(self.candidate1, self.registration)
        self.assertFalse(is_eligible)
        self.assertIn("inactive", reason.lower())

    def test_insufficient_question_bank_is_rejected(self):
        """Test cannot be started if question bank has fewer questions than total_questions."""
        # Delete questions so bank is less than 5
        Question.objects.filter(test=self.test).exclude(question_id__in=[q.question_id for q in self.questions[:3]]).delete()
        self.assertEqual(self.test.questions.count(), 3)

        is_eligible, reason = validate_candidate_eligibility(self.candidate1, self.registration)
        self.assertFalse(is_eligible)
        self.assertIn("does not have enough questions", reason)

    def test_randomized_question_set_contains_configured_number_of_questions(self):
        """Attempt assigns exactly the configured number of questions (5)."""
        attempt = start_attempt_for_registration(self.registration)
        assigned = attempt.attempt_questions.all()
        self.assertEqual(assigned.count(), 5)
        # Unique check
        question_ids = [aq.question_id for aq in assigned]
        self.assertEqual(len(question_ids), len(set(question_ids)))

    def test_assigned_questions_order_is_sequential_and_stable(self):
        """Question orders are 1..5 and remain fixed across page reloads."""
        attempt = start_attempt_for_registration(self.registration)
        assigned = list(attempt.attempt_questions.order_by('question_order'))
        orders = [aq.question_order for aq in assigned]
        self.assertEqual(orders, [1, 2, 3, 4, 5])

        # Second request to start does not re-randomize or create another attempt
        attempt2 = start_attempt_for_registration(self.registration)
        self.assertEqual(attempt.attempt_id, attempt2.attempt_id)
        assigned2 = list(attempt2.attempt_questions.order_by('question_order'))
        self.assertEqual([aq.question_id for aq in assigned], [aq.question_id for aq in assigned2])

    def test_repeated_start_requests_do_not_create_duplicate_attempts(self):
        """Submitting multiple start requests returns the existing in-progress attempt."""
        res1 = self.alice_client.post(reverse('test_start', args=[self.registration.registration_id]))
        res2 = self.alice_client.post(reverse('test_start', args=[self.registration.registration_id]))
        self.assertEqual(TestAttempt.objects.filter(registration=self.registration).count(), 1)


class AnswerAutosaveTests(AssessmentEngineBaseTestCase):
    """Tests for saving answers, validations, and rejection of stale/finalized attempts."""

    def setUp(self):
        super().setUp()
        self.attempt = start_attempt_for_registration(self.registration)
        self.aq1 = self.attempt.attempt_questions.get(question_order=1)

    def test_valid_answer_saves_successfully(self):
        """Candidate can save option 2 for question order 1."""
        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': 2}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['selected_option'], 2)
        self.assertEqual(data['answered_count'], 1)

        self.aq1.refresh_from_db()
        self.assertEqual(self.aq1.selected_option, 2)
        self.assertIsNotNone(self.aq1.answered_at)

    def test_valid_answer_saves_via_json_payload(self):
        """Autosave supports application/json requests."""
        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data='{"question_order": 1, "selected_option": 3}',
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.aq1.refresh_from_db()
        self.assertEqual(self.aq1.selected_option, 3)

    def test_invalid_option_is_rejected(self):
        """Option other than 1, 2, 3, 4 is rejected."""
        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': 99}
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()['success'])

    def test_question_outside_attempt_is_rejected(self):
        """Saving an answer for a question order outside 1..5 is rejected."""
        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 999, 'selected_option': 1}
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()['success'])

    def test_another_candidate_cannot_save_answers(self):
        """Bob cannot autosave answers to Alice's attempt."""
        res = self.bob_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': 1}
        )
        self.assertEqual(res.status_code, 403)

    def test_clear_response_saves_null(self):
        """Sending empty string or null resets selected_option to None."""
        self.aq1.selected_option = 2
        self.aq1.save()

        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': ''}
        )
        self.assertEqual(res.status_code, 200)
        self.aq1.refresh_from_db()
        self.assertIsNone(self.aq1.selected_option)

    def test_autosaved_answers_survive_page_reload(self):
        """Saved responses are populated when re-rendering test interface."""
        self.aq1.selected_option = 2
        self.aq1.save()

        res = self.alice_client.get(reverse('test_take', args=[self.attempt.attempt_id]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'checked')

    def test_answers_cannot_change_after_finalization(self):
        """Once attempt is completed, autosave requests are rejected."""
        self.attempt = evaluate_attempt(self.attempt, submission_reason='manual')
        self.assertEqual(self.attempt.status, 'completed')


        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': 4}
        )
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.json().get('finalized'))


class TimingAndSubmissionTests(AssessmentEngineBaseTestCase):
    """Tests for server-authoritative timer, expiry auto-finalization, and idempotent submission."""

    def setUp(self):
        super().setUp()
        self.attempt = start_attempt_for_registration(self.registration)

    def test_manual_submission_succeeds(self):
        """Candidate submits manually via POST and is redirected to results."""
        res = self.alice_client.post(reverse('test_submit', args=[self.attempt.attempt_id]))
        self.assertRedirects(res, reverse('test_results', args=[self.attempt.attempt_id]))

        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'completed')
        self.assertEqual(self.attempt.submission_reason, 'manual')
        self.assertIsNotNone(self.attempt.score)

    def test_expired_attempt_rejects_answer_and_returns_expiry_json(self):
        """When deadline has passed, autosave rejects modifications and finalizes as expired."""
        # Fast-forward attempt start_time to 40 minutes ago (duration is 30 mins)
        self.attempt.start_time = timezone.now() - timedelta(minutes=40)
        self.attempt.save()
        self.assertTrue(self.attempt.is_expired)

        res = self.alice_client.post(
            reverse('test_autosave', args=[self.attempt.attempt_id]),
            data={'question_order': 1, 'selected_option': 1}
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertTrue(data.get('expired'))

        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'expired')
        self.assertEqual(self.attempt.submission_reason, 'timeout')

    def test_expired_attempt_finalized_on_take_view(self):
        """Accessing test_take after expiry automatically finalizes attempt and redirects to results."""
        self.attempt.start_time = timezone.now() - timedelta(minutes=45)
        self.attempt.save()

        res = self.alice_client.get(reverse('test_take', args=[self.attempt.attempt_id]))
        self.assertRedirects(res, reverse('test_results', args=[self.attempt.attempt_id]))

        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'expired')
        self.assertEqual(self.attempt.submission_reason, 'timeout')

    def test_repeated_submission_is_idempotent(self):
        """Repeated submission calls do not create duplicate scores or alter results."""
        # Answer first 3 questions with correct answer
        aqs = list(self.attempt.attempt_questions.select_related('question').order_by('question_order'))
        for aq in aqs[:3]:
            aq.selected_option = aq.question.correct_option
            aq.save()

        # First submission
        self.attempt = evaluate_attempt(self.attempt, submission_reason='manual')
        first_score = self.attempt.score
        first_end_time = self.attempt.end_time

        # Second submission call
        self.attempt = evaluate_attempt(self.attempt, submission_reason='manual')
        self.assertEqual(self.attempt.score, first_score)
        self.assertEqual(self.attempt.end_time, first_end_time)


    def test_correct_answers_never_revealed_in_assessment_interface(self):
        """Neither test_take nor test_results for candidate expose Question.correct_option in HTML."""
        res_take = self.alice_client.get(reverse('test_take', args=[self.attempt.attempt_id]))
        content_take = res_take.content.decode('utf-8')
        self.assertNotIn("correct_option", content_take)
        self.assertNotIn("Correct Key", content_take)

        evaluate_attempt(self.attempt)
        res_results = self.alice_client.get(reverse('test_results', args=[self.attempt.attempt_id]))
        content_results = res_results.content.decode('utf-8')
        self.assertNotIn("Correct Key", content_results)


class ServerSideEvaluationTests(AssessmentEngineBaseTestCase):
    """Tests for accurate scoring, percentage calculation, pass/fail thresholds, and topic aggregation."""

    def setUp(self):
        super().setUp()
        self.attempt = start_attempt_for_registration(self.registration)

    def test_evaluation_calculates_correct_incorrect_and_unanswered(self):
        """
        Assigned questions (5):
        - Answer 3 correctly
        - Answer 1 incorrectly
        - Leave 1 unanswered
        Expected: score=3, correct=3, incorrect=1, unanswered=1, percentage=60.00%, is_passed=True
        """
        aqs = list(self.attempt.attempt_questions.select_related('question').order_by('question_order'))
        self.assertEqual(len(aqs), 5)

        # 3 correct
        for aq in aqs[:3]:
            aq.selected_option = aq.question.correct_option
            aq.save()

        # 1 incorrect (pick wrong option)
        wrong_opt = (aqs[3].question.correct_option % 4) + 1
        aqs[3].selected_option = wrong_opt
        aqs[3].save()

        # 1 unanswered (leave aqs[4].selected_option as None)

        evaluate_attempt(self.attempt, submission_reason='manual')
        self.attempt.refresh_from_db()

        self.assertEqual(self.attempt.score, 3)
        self.assertEqual(self.attempt.correct_answers, 3)
        self.assertEqual(self.attempt.incorrect_answers, 1)
        self.assertEqual(self.attempt.unanswered, 1)
        self.assertEqual(self.attempt.percentage, Decimal('60.00'))
        self.assertTrue(self.attempt.is_passed)  # 3 >= passing_marks(3)

    def test_failing_boundary_condition(self):
        """Score of 2 on a test with passing_marks=3 marks is_passed as False."""
        aqs = list(self.attempt.attempt_questions.select_related('question').order_by('question_order'))
        # 2 correct, 3 unanswered
        for aq in aqs[:2]:
            aq.selected_option = aq.question.correct_option
            aq.save()

        evaluate_attempt(self.attempt, submission_reason='manual')
        self.attempt.refresh_from_db()

        self.assertEqual(self.attempt.score, 2)
        self.assertEqual(self.attempt.percentage, Decimal('40.00'))
        self.assertFalse(self.attempt.is_passed)

    def test_client_submitted_scores_are_completely_ignored(self):
        """POST request cannot inject client scores."""
        # Attempt to post spoofed scores to submit endpoint
        res = self.alice_client.post(
            reverse('test_submit', args=[self.attempt.attempt_id]),
            data={'score': 999, 'percentage': 100, 'is_passed': True}
        )
        self.attempt.refresh_from_db()
        # All questions were left unanswered, so score must be 0
        self.assertEqual(self.attempt.score, 0)
        self.assertFalse(self.attempt.is_passed)

    def test_topic_performance_aggregation_and_suggestions(self):
        """Topic breakdown groups questions and provides suggestions for missed topics."""
        aqs = list(self.attempt.attempt_questions.select_related('question').order_by('question_order'))
        # Answer first question correct, leave others unanswered
        aqs[0].selected_option = aqs[0].question.correct_option
        aqs[0].save()

        evaluate_attempt(self.attempt)
        topic_perf = get_topic_performance(self.attempt)
        self.assertTrue(len(topic_perf) > 0)

        total_topic_qs = sum(t['total'] for t in topic_perf)
        self.assertEqual(total_topic_qs, 5)


class AuthorizationAndSecurityTests(AssessmentEngineBaseTestCase):
    """Tests for role-based access control and IDOR prevention."""

    def setUp(self):
        super().setUp()
        self.attempt = start_attempt_for_registration(self.registration)
        evaluate_attempt(self.attempt, submission_reason='manual')

    def test_candidate_can_view_their_own_results(self):
        """Candidate Alice can view her own finalized results."""
        res = self.alice_client.get(reverse('test_results', args=[self.attempt.attempt_id]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Results Scorecard")

    def test_candidate_cannot_view_another_candidate_results(self):
        """Candidate Bob receives 403 Forbidden when trying to view Alice's results."""
        res = self.bob_client.get(reverse('test_results', args=[self.attempt.attempt_id]))
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_user_redirected_from_assessment_pages(self):
        """Unauthenticated user is redirected to login for instructions, take, results."""
        r1 = self.anon_client.get(reverse('test_instructions', args=[self.registration.registration_id]))
        self.assertEqual(r1.status_code, 302)

        r2 = self.anon_client.get(reverse('test_take', args=[self.attempt.attempt_id]))
        self.assertEqual(r2.status_code, 302)

        r3 = self.anon_client.get(reverse('test_results', args=[self.attempt.attempt_id]))
        self.assertEqual(r3.status_code, 302)

    def test_administrator_can_inspect_attempt_and_details(self):
        """Authenticated administrator can view the attempts list and detailed audit trail."""
        res_list = self.admin_client.get(
            reverse('admin_test_attempts', args=[self.test.test_id])
        )
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Candidate Alice")

        res_detail = self.admin_client.get(
            reverse('admin_attempt_detail', args=[self.attempt.attempt_id])
        )
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Assigned Questions & Response Audit Trail")
        self.assertContains(res_detail, "Correct Key")

    def test_candidate_cannot_retake_completed_test(self):
        """Attempting to restart an already completed registration redirects to results."""
        res = self.alice_client.post(
            reverse('test_start', args=[self.registration.registration_id])
        )
        self.assertRedirects(res, reverse('test_results', args=[self.attempt.attempt_id]))
        self.assertEqual(TestAttempt.objects.filter(registration=self.registration).count(), 1)
