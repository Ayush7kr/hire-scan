import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.hashers import check_password

from accounts.models import Admin, Candidate, OTPVerification, ActivityLog
from assessments.models import Test, Question, TestRegistration
from attempts.models import TestAttempt, AttemptQuestion


class HomepageTests(TestCase):
    """Test suite for the public-facing homepage."""

    def setUp(self):
        self.client = Client()

    def test_homepage_status_code(self):
        """Homepage must be accessible at root '/' with status 200."""
        response = self.client.get(reverse('homepage'))
        self.assertEqual(response.status_code, 200)

    def test_homepage_contains_required_sections_and_text(self):
        """Homepage must contain the exact approved hero title and key copy."""
        response = self.client.get(reverse('homepage'))
        content = response.content.decode('utf-8')

        self.assertIn('Smarter Technical Assessments', content)
        self.assertIn('Better Hiring Decisions', content)
        self.assertIn('How It Works', content)
        self.assertIn('Features', content)
        self.assertIn('Administrator Login', content)
        self.assertIn('Candidate Login', content)

    def test_homepage_does_not_leak_admin_navigation(self):
        """Public homepage must not expose admin-only management links."""
        response = self.client.get(reverse('homepage'))
        content = response.content.decode('utf-8')
        # Admin dashboard / management links shouldn't be visible in public navigation
        self.assertNotIn('System Overview', content)


class AdminAuthenticationTests(TestCase):
    """Test suite for Administrator login, session creation, and route protection."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Test Super Admin",
            email="admin@test.local"
        )
        self.admin.set_password("SecretPass123!")
        self.admin.save()

    def test_admin_password_is_hashed(self):
        """Admin passwords must never be stored in plaintext."""
        self.assertNotEqual(self.admin.password_hash, "SecretPass123!")
        self.assertTrue(self.admin.password_hash.startswith('pbkdf2_'))
        self.assertTrue(self.admin.check_password("SecretPass123!"))
        self.assertFalse(self.admin.check_password("WrongPassword"))

    def test_admin_login_success(self):
        """Valid admin credentials must set session and redirect to dashboard."""
        response = self.client.post(reverse('admin_login'), {
            'email': 'admin@test.local',
            'password': 'SecretPass123!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.client.session.get('user_role'), ['admin'])
        self.assertEqual(self.client.session.get('admin_id'), str(self.admin.admin_id))

    def test_admin_login_failure_invalid_password(self):
        """Invalid password must show error and not create session."""
        response = self.client.post(reverse('admin_login'), {
            'email': 'admin@test.local',
            'password': 'WrongPassword123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('admin_id'))
        self.assertContains(response, 'Invalid email or password')

    def test_admin_login_failure_nonexistent_email(self):
        """Non-existent email must show generic error without leaking account existence."""
        response = self.client.post(reverse('admin_login'), {
            'email': 'ghost@test.local',
            'password': 'AnyPassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('admin_id'))
        self.assertContains(response, 'Invalid email or password')

    def test_admin_dashboard_protected_against_unauthenticated_access(self):
        """Unauthenticated requests to admin dashboard must redirect to admin login."""
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin_login'), response.url)

    def test_admin_dashboard_accessible_when_authenticated(self):
        """Authenticated admins can access the dashboard."""
        self.client.post(reverse('admin_login'), {
            'email': 'admin@test.local',
            'password': 'SecretPass123!'
        })
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Overview')
        self.assertContains(response, 'Total Candidates')

    def test_admin_logout_clears_session(self):
        """Admin logout must invalidate the session."""
        self.client.post(reverse('admin_login'), {
            'email': 'admin@test.local',
            'password': 'SecretPass123!'
        })
        response = self.client.get(reverse('admin_logout'))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.client.session.get('admin_id'))


class CandidateAuthenticationTests(TestCase):
    """Test suite for Candidate passwordless OTP email authentication."""

    def setUp(self):
        self.client = Client()
        self.candidate = Candidate.objects.create(
            name="Alice Candidate",
            email="alice@candidate.local",
            whatsapp_number="9876543210",
            college_name_address="National Institute of Technology",
            qualification="B.Tech Computer Science",
            passing_year=2025
        )

    def test_send_otp_success_for_registered_candidate(self):
        """Sending OTP for a registered candidate creates a hashed record and sends email."""
        response = self.client.post(reverse('candidate_send_otp'), {
            'email': 'alice@candidate.local'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify OTP record in database
        otp_record = OTPVerification.objects.filter(candidate=self.candidate).first()
        self.assertIsNotNone(otp_record)
        self.assertFalse(otp_record.is_used)
        # Verify OTP is hashed
        self.assertTrue(otp_record.otp_hash.startswith('pbkdf2_'))

    def test_send_otp_safe_response_for_unregistered_email(self):
        """Non-registered emails receive same message to prevent enumeration."""
        response = self.client.post(reverse('candidate_send_otp'), {
            'email': 'unknown@random.org'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # No OTP record created
        self.assertEqual(OTPVerification.objects.count(), 0)

    def test_candidate_verify_otp_success(self):
        """Verifying with correct OTP establishes session and redirects."""
        # Create an OTP
        otp_record = OTPVerification(
            candidate=self.candidate,
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        raw_code = "123456"
        otp_record.set_otp(raw_code)
        otp_record.save()

        # Set session as if send_otp was called
        session = self.client.session
        session['otp_email'] = self.candidate.email
        session.save()

        # Verify OTP
        response = self.client.post(reverse('candidate_verify_otp'), {
            'otp': raw_code
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(self.client.session.get('user_role'), 'candidate')
        self.assertEqual(self.client.session.get('candidate_id'), str(self.candidate.candidate_id))

        # OTP marked as used
        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_used)

    def test_candidate_verify_otp_invalid_code(self):
        """Incorrect OTP code is rejected and increments attempt count."""
        otp_record = OTPVerification(
            candidate=self.candidate,
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        otp_record.set_otp("123456")
        otp_record.save()

        session = self.client.session
        session['otp_email'] = self.candidate.email
        session.save()

        response = self.client.post(reverse('candidate_verify_otp'), {
            'otp': '999999'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid OTP', data['error'])

        otp_record.refresh_from_db()
        self.assertEqual(otp_record.attempts, 1)

    def test_candidate_verify_otp_expired(self):
        """Expired OTP is rejected."""
        otp_record = OTPVerification(
            candidate=self.candidate,
            expires_at=timezone.now() - timedelta(minutes=1)  # expired
        )
        otp_record.set_otp("123456")
        otp_record.save()

        session = self.client.session
        session['otp_email'] = self.candidate.email
        session.save()

        response = self.client.post(reverse('candidate_verify_otp'), {
            'otp': '123456'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('expired', data['error'].lower())

    def test_candidate_dashboard_protected(self):
        """Unauthenticated candidate cannot access dashboard."""
        response = self.client.get(reverse('candidate_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('candidate_login'), response.url)


class DatabaseIntegrityAndConstraintsTests(TestCase):
    """Test suite validating database constraints from the approved ER diagram."""

    def test_candidate_email_uniqueness(self):
        """Candidate email must be strictly unique."""
        Candidate.objects.create(name="Cand 1", email="unique@candidate.local")
        with self.assertRaises(Exception):
            Candidate.objects.create(name="Cand 2", email="unique@candidate.local")

    def test_admin_email_uniqueness(self):
        """Admin email must be strictly unique."""
        Admin.objects.create(name="Admin 1", email="unique@admin.local", password_hash="hash1")
        with self.assertRaises(Exception):
            Admin.objects.create(name="Admin 2", email="unique@admin.local", password_hash="hash2")

    def test_test_registration_uniqueness(self):
        """A candidate can only be registered once for a given test (UNIQUE(candidate, test))."""
        candidate = Candidate.objects.create(name="Cand Test", email="testreg@candidate.local")
        test = Test.objects.create(
            test_name="Python Core",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=True
        )
        TestRegistration.objects.create(candidate=candidate, test=test)

        with self.assertRaises(Exception):
            TestRegistration.objects.create(candidate=candidate, test=test)

    def test_test_attempt_one_to_one_registration(self):
        """Each registration can have at most one attempt (OneToOneField constraint)."""
        candidate = Candidate.objects.create(name="Cand Attempt", email="attempt@candidate.local")
        test = Test.objects.create(
            test_name="Django Assessment",
            duration_minutes=45,
            total_questions=15,
            passing_marks=9,
            is_active=True
        )
        reg = TestRegistration.objects.create(candidate=candidate, test=test)
        TestAttempt.objects.create(registration=reg)

        with self.assertRaises(Exception):
            TestAttempt.objects.create(registration=reg)
