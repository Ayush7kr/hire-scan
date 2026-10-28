import io
from datetime import timedelta
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration, NotificationLog
from attempts.models import TestAttempt


class TestManagementTests(TestCase):
    """Test suite for Test CRUD, sufficiency enforcement, and activation rules."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Admin Test Manager",
            email="admin.tests@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.client.post(reverse('admin_login'), {
            'email': 'admin.tests@test.local',
            'password': 'AdminPass123!'
        })

    def test_test_list_requires_admin_auth(self):
        """Unauthenticated requests to test list redirect to admin login."""
        anon = Client()
        res = anon.get(reverse('test_list'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('admin_login'), res.url)

    def test_create_test_success(self):
        """Creating a test with valid parameters stores it as inactive."""
        response = self.client.post(reverse('test_create'), {
            'test_name': 'Full Stack Django & Python',
            'description': 'Assess core backend and full-stack architecture.',
            'duration_minutes': '45',
            'total_questions': '15',
            'passing_marks': '9'
        })
        self.assertEqual(response.status_code, 302)
        test = Test.objects.filter(test_name='Full Stack Django & Python').first()
        self.assertIsNotNone(test)
        self.assertEqual(test.duration_minutes, 45)
        self.assertEqual(test.total_questions, 15)
        self.assertEqual(test.passing_marks, 9)
        self.assertFalse(test.is_active)  # initialized inactive

    def test_create_test_validation_errors(self):
        """Invalid duration, total questions, or passing marks > questions are rejected."""
        # Empty name
        res1 = self.client.post(reverse('test_create'), {
            'test_name': '',
            'duration_minutes': '30',
            'total_questions': '10',
            'passing_marks': '5'
        })
        self.assertEqual(res1.status_code, 200)
        self.assertContains(res1, 'Test name is required')

        # Invalid duration <= 0
        res2 = self.client.post(reverse('test_create'), {
            'test_name': 'Valid Name',
            'duration_minutes': '0',
            'total_questions': '10',
            'passing_marks': '5'
        })
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, 'Duration must be greater than 0')

        # Passing marks > total questions
        res3 = self.client.post(reverse('test_create'), {
            'test_name': 'Valid Name 2',
            'duration_minutes': '30',
            'total_questions': '10',
            'passing_marks': '15'  # 15 > 10!
        })
        self.assertEqual(res3.status_code, 200)
        self.assertContains(res3, 'Passing marks cannot exceed total questions')

    def test_test_activation_rejected_with_insufficient_questions(self):
        """A test CANNOT be activated if question bank count < total_questions."""
        test = Test.objects.create(
            test_name="Insufficient Test",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=False
        )
        # Upload only 2 questions (need 10)
        for i in range(2):
            Question.objects.create(
                test=test,
                question_text=f"Sample Question {i}",
                option1="A", option2="B", option3="C", option4="D",
                correct_option=1, topic="Basics"
            )

        # Attempt to activate
        res = self.client.post(reverse('test_toggle_status', kwargs={'test_id': test.test_id}))
        self.assertEqual(res.status_code, 302)

        test.refresh_from_db()
        self.assertFalse(test.is_active)  # Must remain inactive!

    def test_test_activation_succeeds_with_sufficient_questions(self):
        """A test can be activated when question bank count >= total_questions."""
        test = Test.objects.create(
            test_name="Sufficient Test",
            duration_minutes=30,
            total_questions=3,
            passing_marks=2,
            is_active=False
        )
        for i in range(3):
            Question.objects.create(
                test=test,
                question_text=f"Question {i}",
                option1="Opt1", option2="Opt2", option3="Opt3", option4="Opt4",
                correct_option=1, topic="Core"
            )

        res = self.client.post(reverse('test_toggle_status', kwargs={'test_id': test.test_id}))
        self.assertEqual(res.status_code, 302)

        test.refresh_from_db()
        self.assertTrue(test.is_active)  # Activated!

        # Deactivate
        res2 = self.client.post(reverse('test_toggle_status', kwargs={'test_id': test.test_id}))
        self.assertEqual(res2.status_code, 302)
        test.refresh_from_db()
        self.assertFalse(test.is_active)  # Deactivated!


class QuestionBankTests(TestCase):
    """Test suite for question bank CRUD, CSV upload, normalization, and validation."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Admin Questions",
            email="admin.q@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.client.post(reverse('admin_login'), {
            'email': 'admin.q@test.local',
            'password': 'AdminPass123!'
        })

        self.test = Test.objects.create(
            test_name="Database & SQL Test",
            duration_minutes=20,
            total_questions=5,
            passing_marks=3,
            is_active=False
        )

    def test_question_template_download(self):
        """Downloading question template returns CSV with expected column headers."""
        response = self.client.get(reverse('question_template_download'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('question,option1,option2,option3,option4,correct_option,topic', content)

    def test_question_csv_import_valid_and_normalization(self):
        """
        Uploading a question bank CSV correctly parses rows, normalizes A/B/C/D to 1/2/3/4,
        and saves questions linked strictly to the target test.
        """
        csv_data = (
            "question,option1,option2,option3,option4,correct_option,topic,difficulty,suggestions\n"
            "What does SQL stand for?,Structured Query Language,Simple Query Language,Standard Query Level,Sequential Query Logic,1,Databases,easy,Study SQL fundamentals\n"
            "Which clause is used to filter group results?,WHERE,ORDER BY,HAVING,GROUP BY,C,SQL Clauses,medium,Review aggregate filter HAVING clause\n"
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'questions.csv'

        response = self.client.post(
            reverse('question_import', kwargs={'test_id': self.test.test_id}),
            {'csv_file': csv_file}
        )
        self.assertEqual(response.status_code, 200)

        # Check questions created
        self.assertEqual(Question.objects.filter(test=self.test).count(), 2)

        q1 = Question.objects.get(test=self.test, topic='Databases')
        self.assertEqual(q1.correct_option, 1)

        # Check normalization: 'C' was converted to 3!
        q2 = Question.objects.get(test=self.test, topic='SQL Clauses')
        self.assertEqual(q2.correct_option, 3)

    def test_question_csv_import_invalid_correct_option_and_missing_fields(self):
        """Rows with invalid correct_option or missing options are rejected."""
        csv_data = (
            "question,option1,option2,option3,option4,correct_option,topic\n"
            "Bad Option Question,A,B,C,D,9,Testing\n"  # 9 is invalid!
            "Missing Option Question,A,B,C,,1,Testing\n"  # option 4 is empty!
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'bad_questions.csv'

        response = self.client.post(
            reverse('question_import', kwargs={'test_id': self.test.test_id}),
            {'csv_file': csv_file}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid correct_option')
        self.assertContains(response, 'Option 4 is missing')
        self.assertEqual(Question.objects.filter(test=self.test).count(), 0)

    def test_question_delete_auto_deactivates_insufficient_test(self):
        """Deleting a question from an active test deactivates it if bank size falls below required."""
        # Setup 2 questions for test with total_questions=2
        self.test.total_questions = 2
        self.test.save()

        q1 = Question.objects.create(
            test=self.test, question_text="Q1",
            option1="1", option2="2", option3="3", option4="4", correct_option=1, topic="T1"
        )
        q2 = Question.objects.create(
            test=self.test, question_text="Q2",
            option1="1", option2="2", option3="3", option4="4", correct_option=1, topic="T2"
        )
        self.test.is_active = True
        self.test.save()

        # Delete q2 -> bank size becomes 1 (< 2)
        res = self.client.post(reverse('question_delete', kwargs={'test_id': self.test.test_id, 'question_id': q2.question_id}))
        self.assertEqual(res.status_code, 302)

        self.test.refresh_from_db()
        self.assertFalse(self.test.is_active)  # Automatically deactivated!


class RegistrationManagementTests(TestCase):
    """Test suite for Candidate-to-Test registrations, uniqueness, and cancellation."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Admin Registration",
            email="admin.reg@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.client.post(reverse('admin_login'), {
            'email': 'admin.reg@test.local',
            'password': 'AdminPass123!'
        })

        self.candidate = Candidate.objects.create(
            name="Test Examinee",
            email="examinee@test.local"
        )
        self.test = Test.objects.create(
            test_name="Web Systems Test",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )

    def test_create_registration_success(self):
        """Admin can register an eligible candidate for a test."""
        response = self.client.post(reverse('registration_create'), {
            'candidate_id': str(self.candidate.candidate_id),
            'test_id': str(self.test.test_id)
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TestRegistration.objects.filter(candidate=self.candidate, test=self.test).exists())

    def test_create_registration_duplicate_rejected(self):
        """Registering the same candidate for the same test twice is rejected with friendly error."""
        TestRegistration.objects.create(candidate=self.candidate, test=self.test)

        response = self.client.post(reverse('registration_create'), {
            'candidate_id': str(self.candidate.candidate_id),
            'test_id': str(self.test.test_id)
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already registered')
        self.assertEqual(TestRegistration.objects.filter(candidate=self.candidate, test=self.test).count(), 1)

    def test_cancel_registration_success(self):
        """Admin can cancel a candidate's registration if no completed attempt exists."""
        reg = TestRegistration.objects.create(candidate=self.candidate, test=self.test, status='registered')

        response = self.client.post(reverse('registration_cancel', kwargs={'registration_id': reg.registration_id}))
        self.assertEqual(response.status_code, 302)

        reg.refresh_from_db()
        self.assertEqual(reg.status, 'cancelled')

    def test_cancel_registration_prevented_if_attempt_completed(self):
        """Cancellation is rejected if the candidate already completed the assessment."""
        reg = TestRegistration.objects.create(candidate=self.candidate, test=self.test, status='registered')
        TestAttempt.objects.create(
            registration=reg,
            status='completed',
            score=8,
            percentage=80.0
        )

        response = self.client.post(reverse('registration_cancel', kwargs={'registration_id': reg.registration_id}))
        self.assertEqual(response.status_code, 302)

        reg.refresh_from_db()
        self.assertEqual(reg.status, 'registered')  # Must remain registered!


class BulkRegistrationTests(TestCase):
    """Test suite for mentor-requested multiple candidate selection in test registration."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(name="Bulk Admin", email="bulk.admin@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()
        self.client.post(reverse('admin_login'), {
            'email': 'bulk.admin@test.local',
            'password': 'AdminPass123!'
        })

        self.test = Test.objects.create(
            test_name="Full-Stack Registration Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )

        self.cand1 = Candidate.objects.create(name="Candidate One", email="cand1@test.local", is_active=True)
        self.cand2 = Candidate.objects.create(name="Candidate Two", email="cand2@test.local", is_active=True)
        self.cand3 = Candidate.objects.create(name="Candidate Three", email="cand3@test.local", is_active=True)
        self.cand_inactive = Candidate.objects.create(name="Inactive Candidate", email="inactive@test.local", is_active=False)

    def test_bulk_registration_success(self):
        """Admin can select and register multiple active candidates in a single atomic transaction."""
        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': [str(self.cand1.candidate_id), str(self.cand2.candidate_id), str(self.cand3.candidate_id)]
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TestRegistration.objects.filter(test=self.test).count(), 3)
        self.assertTrue(TestRegistration.objects.filter(test=self.test, candidate=self.cand1).exists())
        self.assertTrue(TestRegistration.objects.filter(test=self.test, candidate=self.cand2).exists())
        self.assertTrue(TestRegistration.objects.filter(test=self.test, candidate=self.cand3).exists())

    def test_bulk_registration_partial_duplicates_reported_clearly(self):
        """If one candidate is already registered, new candidates are registered and duplicate is reported with warning."""
        TestRegistration.objects.create(test=self.test, candidate=self.cand1, status='registered')

        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': [str(self.cand1.candidate_id), str(self.cand2.candidate_id)]
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        # cand2 created, cand1 duplicate reported
        self.assertEqual(TestRegistration.objects.filter(test=self.test).count(), 2)
        content = response.content.decode('utf-8')
        self.assertIn('Successfully registered 1 candidate', content)
        self.assertIn('already registered', content)

    def test_bulk_registration_rejects_inactive_candidates(self):
        """Inactive candidates are rejected with clear rejection reason."""
        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': [str(self.cand_inactive.candidate_id)]
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TestRegistration.objects.filter(test=self.test).count(), 0)
        content = response.content.decode('utf-8')
        self.assertIn('Candidate is inactive', content)

    def test_bulk_registration_rejects_malformed_candidate_id(self):
        """Malformed UUID string is caught safely without unhandled exception."""
        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': ['not-a-valid-uuid-12345']
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TestRegistration.objects.filter(test=self.test).count(), 0)
        content = response.content.decode('utf-8')
        self.assertIn('Malformed candidate ID', content)

    def test_bulk_registration_rejects_empty_selection(self):
        """Empty candidate selection triggers clear validation error."""
        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': []
        })
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Please select at least one candidate', content)


class TestStatusTrackingTests(TestCase):
    """Test suite for the 5 mentor-requested test statuses and time-boundary rules."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(name="Status Admin", email="status.admin@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()
        self.client.post(reverse('admin_login'), {
            'email': 'status.admin@test.local',
            'password': 'AdminPass123!'
        })

    def test_status_cancelled_precedence(self):
        """Cancelled tests always have status 'cancelled' regardless of schedule or active flag."""
        now = timezone.now()
        test = Test.objects.create(
            test_name="Cancelled Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
            is_active=True,
            is_cancelled=True
        )
        self.assertEqual(test.status, 'cancelled')
        self.assertEqual(test.status_display, 'Cancelled')

    def test_status_completed_when_end_time_passed(self):
        """Active test whose end_time has passed has status 'completed'."""
        now = timezone.now()
        test = Test.objects.create(
            test_name="Expired Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(minutes=5),
            is_active=True,
            is_cancelled=False
        )
        self.assertEqual(test.status, 'completed')
        self.assertEqual(test.status_display, 'Completed')

    def test_status_upcoming_when_start_time_in_future(self):
        """Active test whose start_time is in the future has status 'upcoming'."""
        now = timezone.now()
        test = Test.objects.create(
            test_name="Upcoming Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=5),
            is_active=True,
            is_cancelled=False
        )
        self.assertEqual(test.status, 'upcoming')
        self.assertEqual(test.status_display, 'Upcoming')

    def test_status_in_progress_during_active_window(self):
        """Active test within [start_time, end_time] has status 'in_progress'."""
        now = timezone.now()
        test = Test.objects.create(
            test_name="Live Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            start_time=now - timedelta(minutes=15),
            end_time=now + timedelta(minutes=45),
            is_active=True,
            is_cancelled=False
        )
        self.assertEqual(test.status, 'in_progress')
        self.assertEqual(test.status_display, 'In Progress')

    def test_status_scheduled_when_inactive(self):
        """Test with is_active=False is considered 'scheduled'."""
        test = Test.objects.create(
            test_name="Draft Scheduled Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=False,
            is_cancelled=False
        )
        self.assertEqual(test.status, 'scheduled')
        self.assertEqual(test.status_display, 'Scheduled')

    def test_admin_toggle_cancel_test_action(self):
        """Admin can cancel and uncancel a test via POST action."""
        test = Test.objects.create(
            test_name="Cancelable Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )
        # Cancel
        res1 = self.client.post(reverse('test_toggle_cancel', kwargs={'test_id': test.test_id}))
        self.assertEqual(res1.status_code, 302)
        test.refresh_from_db()
        self.assertTrue(test.is_cancelled)
        self.assertFalse(test.is_active)
        self.assertEqual(test.status, 'cancelled')

        # Uncancel
        res2 = self.client.post(reverse('test_toggle_cancel', kwargs={'test_id': test.test_id}))
        self.assertEqual(res2.status_code, 302)
        test.refresh_from_db()
        self.assertFalse(test.is_cancelled)


class SearchAndFilterTests(TestCase):
    """Test suite for server-side search, filtering, and query string preservation."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(name="Search Admin", email="search.admin@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()
        self.client.post(reverse('admin_login'), {
            'email': 'search.admin@test.local',
            'password': 'AdminPass123!'
        })

        self.test_py = Test.objects.create(
            test_name="Python Automation",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )
        self.test_js = Test.objects.create(
            test_name="JavaScript React",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=False
        )

        self.cand_alice = Candidate.objects.create(name="Alice Walker", email="alice.walker@test.local", is_active=True)
        self.cand_bob = Candidate.objects.create(name="Bob Smith", email="bob.smith@test.local", is_active=True)

        self.reg_alice = TestRegistration.objects.create(test=self.test_py, candidate=self.cand_alice, status='registered')
        self.reg_bob = TestRegistration.objects.create(test=self.test_js, candidate=self.cand_bob, status='cancelled')

    def test_search_registrations_by_candidate_name_and_test(self):
        """Admin can search registrations by candidate name or test title."""
        # Search candidate name
        res1 = self.client.get(reverse('registration_list'), {'q': 'Alice'})
        self.assertContains(res1, 'Alice Walker')
        self.assertNotContains(res1, 'Bob Smith')

        # Search test name
        res2 = self.client.get(reverse('registration_list'), {'q': 'JavaScript'})
        self.assertContains(res2, 'Bob Smith')
        self.assertNotContains(res2, 'Alice Walker')
        self.assertIn(self.reg_bob, res2.context['page_obj'])
        self.assertNotIn(self.reg_alice, res2.context['page_obj'])

    def test_filter_registrations_by_status(self):
        """Admin can filter registrations by status."""
        res_cancelled = self.client.get(reverse('registration_list'), {'status': 'cancelled'})
        self.assertContains(res_cancelled, 'Bob Smith')
        self.assertNotContains(res_cancelled, 'Alice Walker')

        res_registered = self.client.get(reverse('registration_list'), {'status': 'registered'})
        self.assertContains(res_registered, 'Alice Walker')
        self.assertNotContains(res_registered, 'Bob Smith')

    def test_test_list_filter_by_status(self):
        """Admin can filter tests by derived test status."""
        res_sched = self.client.get(reverse('test_list'), {'status': 'scheduled'})
        self.assertContains(res_sched, 'JavaScript React')
        self.assertNotContains(res_sched, 'Python Automation')

        res_prog = self.client.get(reverse('test_list'), {'status': 'in_progress'})
        self.assertContains(res_prog, 'Python Automation')
        self.assertNotContains(res_prog, 'JavaScript React')

    def test_pagination_preserves_query_parameters(self):
        """Context provides query_string preserving search and filter criteria for pagination links."""
        res = self.client.get(reverse('registration_list'), {'q': 'Alice', 'status': 'registered'})
        self.assertIn('query_string', res.context)
        self.assertIn('q=Alice', res.context['query_string'])
        self.assertIn('status=registered', res.context['query_string'])


class BulkRegistrationSummaryTests(TestCase):
    """Test suite for mentor-requested bulk registration summary reporting and session handling."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(name="Summary Admin", email="summary.admin@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()
        self.client.post(reverse('admin_login'), {
            'email': 'summary.admin@test.local',
            'password': 'AdminPass123!'
        })

        self.test = Test.objects.create(
            test_name="Bulk Summary Assessment",
            duration_minutes=45,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )

        self.cand_new = Candidate.objects.create(name="New Candidate", email="new.cand@test.local", is_active=True)
        self.cand_existing = Candidate.objects.create(name="Existing Candidate", email="existing.cand@test.local", is_active=True)
        self.cand_inactive = Candidate.objects.create(name="Disabled Candidate", email="disabled.cand@test.local", is_active=False)

        # Pre-register cand_existing
        TestRegistration.objects.create(test=self.test, candidate=self.cand_existing, status='registered')

    def test_direct_access_without_session_redirects_to_registration_list(self):
        """Visiting the summary endpoint without an active session summary redirects to registration list."""
        response = self.client.get(reverse('registration_bulk_summary'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('registration_list'), response.url)

    def test_bulk_registration_redirects_to_summary_and_renders_breakdown(self):
        """Bulk registration populates session and renders summary with success, duplicate, and rejected breakdowns."""
        response = self.client.post(reverse('registration_create'), {
            'mode': 'multiple',
            'test_id': str(self.test.test_id),
            'candidate_ids': [
                str(self.cand_new.candidate_id),
                str(self.cand_existing.candidate_id),
                str(self.cand_inactive.candidate_id)
            ]
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('registration_bulk_summary'))

        # Follow redirect to summary page
        summary_response = self.client.get(reverse('registration_bulk_summary'))
        self.assertEqual(summary_response.status_code, 200)

        # Check KPI metrics
        summary = summary_response.context['summary']
        self.assertEqual(summary['total_selected'], 3)
        self.assertEqual(summary['created_count'], 1)
        self.assertEqual(summary['already_registered_count'], 1)
        self.assertEqual(summary['rejected_count'], 1)

        # Check candidate attribution in tables
        content = summary_response.content.decode('utf-8')
        self.assertIn('New Candidate', content)
        self.assertIn('Existing Candidate', content)
        self.assertIn('Disabled Candidate', content)
        self.assertIn('Candidate is inactive', content)

        # Refreshing the summary page keeps the report visible for printing or review
        repeat_response = self.client.get(reverse('registration_bulk_summary'))
        self.assertEqual(repeat_response.status_code, 200)

        # When session key is cleared, direct access redirects to list
        session = self.client.session
        del session['bulk_registration_summary']
        session.save()
        subsequent_response = self.client.get(reverse('registration_bulk_summary'))
        self.assertEqual(subsequent_response.status_code, 302)
        self.assertIn(reverse('registration_list'), subsequent_response.url)


class AssessmentNotificationTests(TestCase):
    """Test suite for assessment email notifications, anti-duplication, and reminders."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(name="Notification Admin", email="notify.admin@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()
        self.client.post(reverse('admin_login'), {
            'email': 'notify.admin@test.local',
            'password': 'AdminPass123!'
        })

        self.candidate = Candidate.objects.create(
            name="Notified Candidate",
            email="candidate.notify@test.local",
            is_active=True
        )
        self.test = Test.objects.create(
            test_name="Notification Verification Test",
            duration_minutes=30,
            total_questions=5,
            passing_marks=3,
            is_active=True
        )

    def test_single_registration_dispatches_email_and_logs(self):
        """Registering a candidate sends an email and logs to NotificationLog."""
        mail.outbox.clear()

        response = self.client.post(reverse('registration_create'), {
            'candidate_id': str(self.candidate.candidate_id),
            'test_id': str(self.test.test_id)
        })
        self.assertEqual(response.status_code, 302)

        # Verify email sent
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Notification Verification Test", email.subject)
        self.assertIn("Notified Candidate", email.body)
        self.assertEqual(email.to, ["candidate.notify@test.local"])

        # Verify NotificationLog entry
        log_entry = NotificationLog.objects.filter(
            candidate=self.candidate,
            test=self.test,
            notification_type='registered'
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.status, 'sent')

    def test_registration_notification_prevents_duplicate_sends(self):
        """Retrying or invoking notification helper again prevents sending duplicate email."""
        from assessments.notifications import send_registration_notification

        TestRegistration.objects.create(candidate=self.candidate, test=self.test, status='registered')
        mail.outbox.clear()

        # First call: succeeds and sends email
        success1, msg1 = send_registration_notification(self.candidate, self.test)
        self.assertTrue(success1)
        self.assertEqual(len(mail.outbox), 1)

        # Second call: detected as duplicate, sends no new email
        success2, msg2 = send_registration_notification(self.candidate, self.test)
        self.assertIn("already delivered", msg2)
        self.assertEqual(len(mail.outbox), 1)

    def test_test_activation_dispatches_available_notification(self):
        """Activating an inactive test with registered candidates sends 'available' notification."""
        test_inactive = Test.objects.create(
            test_name="Pending Activation Test",
            duration_minutes=30,
            total_questions=2,
            passing_marks=1,
            is_active=False
        )
        for i in range(2):
            Question.objects.create(
                test=test_inactive,
                question_text=f"Q{i}",
                option1="1", option2="2", option3="3", option4="4",
                correct_option=1, topic="T"
            )
        TestRegistration.objects.create(candidate=self.candidate, test=test_inactive, status='registered')

        mail.outbox.clear()
        res = self.client.post(reverse('test_toggle_status', kwargs={'test_id': test_inactive.test_id}))
        self.assertEqual(res.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Pending Activation Test", email.subject)
        self.assertIn("now Open", email.subject)

        # Check log
        self.assertTrue(NotificationLog.objects.filter(
            candidate=self.candidate,
            test=test_inactive,
            notification_type='available',
            status='sent'
        ).exists())

    def test_test_cancellation_dispatches_cancelled_notification(self):
        """Cancelling a test sends 'cancelled' notification to registered candidates."""
        TestRegistration.objects.create(candidate=self.candidate, test=self.test, status='registered')
        mail.outbox.clear()

        res = self.client.post(reverse('test_toggle_cancel', kwargs={'test_id': self.test.test_id}))
        self.assertEqual(res.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Notification Verification Test", email.subject)
        self.assertIn("Cancelled", email.subject)

        self.assertTrue(NotificationLog.objects.filter(
            candidate=self.candidate,
            test=self.test,
            notification_type='cancelled',
            status='sent'
        ).exists())

    def test_send_assessment_reminders_command(self):
        """send_assessment_reminders command alerts candidates with upcoming scheduled tests."""
        now = timezone.now()
        upcoming_test = Test.objects.create(
            test_name="Upcoming Timed Exam",
            duration_minutes=60,
            total_questions=10,
            passing_marks=6,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=6),
            is_active=True
        )
        TestRegistration.objects.create(candidate=self.candidate, test=upcoming_test, status='registered')

        mail.outbox.clear()

        # Run command with hours=5
        call_command('send_assessment_reminders', hours=5)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Reminder", email.subject)
        self.assertIn("Upcoming Timed Exam", email.subject)

        self.assertTrue(NotificationLog.objects.filter(
            candidate=self.candidate,
            test=upcoming_test,
            notification_type='reminder',
            status='sent'
        ).exists())

        # Second run should send 0 emails due to deduplication
        call_command('send_assessment_reminders', hours=5)
        self.assertEqual(len(mail.outbox), 1)


class NotificationDeliveryMonitorTests(TestCase):
    """Test suite for Notification Delivery Monitoring and Safe Retry Mechanisms."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin.objects.create(name="Notification Admin", email="admin.notif@test.local")
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.client.post(reverse('admin_login'), {
            'email': 'admin.notif@test.local',
            'password': 'AdminPass123!'
        })

        self.candidate = Candidate.objects.create(
            name="Charlie Candidate",
            email="charlie.notif@test.local",
            is_active=True
        )
        self.test = Test.objects.create(
            test_name="Security Engineering Test",
            duration_minutes=60,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )
        self.reg = TestRegistration.objects.create(candidate=self.candidate, test=self.test, status='registered')

        self.failed_log = NotificationLog.objects.create(
            candidate=self.candidate,
            test=self.test,
            notification_type='registered',
            recipient_email=self.candidate.email,
            subject="Test Registration Notice",
            status='failed',
            error_message="SMTP connection refused"
        )
        self.sent_log = NotificationLog.objects.create(
            candidate=self.candidate,
            test=self.test,
            notification_type='reminder',
            recipient_email=self.candidate.email,
            subject="Test Reminder Notice",
            status='sent'
        )

    def test_notification_list_unauthenticated_redirects(self):
        """Unauthenticated requests to notification list redirect to admin login."""
        anon = Client()
        response = anon.get(reverse('notification_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin_login'), response.url)

    def test_notification_list_view_renders_for_admin(self):
        """Notification list displays delivery statuses, metrics, and logs."""
        response = self.client.get(reverse('notification_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Notification Delivery Monitor')
        self.assertContains(response, 'charlie.notif@test.local')
        self.assertContains(response, 'Security Engineering Test')
        self.assertContains(response, 'Failed')
        self.assertContains(response, 'Sent')
        self.assertEqual(response.context['total_count'], 2)
        self.assertEqual(response.context['failed_count'], 1)
        self.assertEqual(response.context['sent_count'], 1)

    def test_notification_list_filter_by_status(self):
        """Filter notifications by failed and sent delivery statuses."""
        res_failed = self.client.get(reverse('notification_list'), {'status': 'failed'})
        self.assertEqual(res_failed.status_code, 200)
        self.assertContains(res_failed, 'SMTP connection refused')
        self.assertNotContains(res_failed, 'Test Reminder Notice')

        res_sent = self.client.get(reverse('notification_list'), {'status': 'sent'})
        self.assertEqual(res_sent.status_code, 200)
        self.assertContains(res_sent, 'Test Reminder Notice')
        self.assertNotContains(res_sent, 'SMTP connection refused')

    def test_notification_list_search_query(self):
        """Search query filters by recipient email or test name."""
        response = self.client.get(reverse('notification_list'), {'q': 'charlie'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'charlie.notif@test.local')

    def test_notification_retry_successful(self):
        """Retrying a failed notification dispatches email and updates log to sent."""
        mail.outbox.clear()
        response = self.client.post(reverse('notification_retry', kwargs={'log_id': self.failed_log.notification_id}))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('notification_list'))

        self.failed_log.refresh_from_db()
        self.assertEqual(self.failed_log.status, 'sent')
        self.assertEqual(self.failed_log.error_message, '')

        # Audit log created
        self.assertTrue(ActivityLog.objects.filter(
            admin=self.admin,
            activity_type='notification_retried'
        ).exists())

    def test_notification_retry_already_sent_is_rejected(self):
        """Retrying an already sent notification is idempotent and does not resend."""
        mail.outbox.clear()
        response = self.client.post(reverse('notification_retry', kwargs={'log_id': self.sent_log.notification_id}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_notification_retry_inactive_candidate_rejected(self):
        """Deactivated candidate notifications cannot be retried."""
        self.candidate.is_active = False
        self.candidate.save()

        response = self.client.post(reverse('notification_retry', kwargs={'log_id': self.failed_log.notification_id}))
        self.assertEqual(response.status_code, 302)
        self.failed_log.refresh_from_db()
        self.assertEqual(self.failed_log.status, 'failed')

    def test_question_import_error_csv_formula_injection_defense(self):
        """Question error CSV sanitizes cells containing formula trigger prefixes."""
        session = self.client.session
        session['question_import_errors'] = [
            {'row': 2, 'question': '=SUM(A1:A10)', 'topic': '@Math', 'reason': '+Invalid format'}
        ]
        session.save()

        response = self.client.get(reverse('question_import_error_csv'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("row_number,question,topic,error_reason", content)
        self.assertIn("'=SUM(A1:A10)", content)
        self.assertIn("'@Math", content)
        self.assertIn("'+Invalid format", content)


