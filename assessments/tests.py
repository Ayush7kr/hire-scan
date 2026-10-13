import io
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration
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
