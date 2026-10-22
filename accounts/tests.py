import uuid
import smtplib
from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core import mail
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

    def test_send_otp_email_dispatch_and_outbox_content(self):
        """Successful OTP generation dispatches an email with subject, body, and recipient."""
        mail.outbox.clear()
        response = self.client.post(reverse('candidate_send_otp'), {
            'email': 'alice@candidate.local'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify email dispatched to outbox
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.subject, 'HireScan — Your Login OTP')
        self.assertEqual(sent_email.to, ['alice@candidate.local'])
        self.assertIn('one-time login code is:', sent_email.body)
        self.assertIn('expires in', sent_email.body)

    @patch('accounts.views.send_mail')
    def test_send_otp_smtp_failure_handling(self, mock_send_mail):
        """When SMTP dispatch fails, user gets generic error and unsent OTP is deleted."""
        mock_send_mail.side_effect = smtplib.SMTPException("SMTP connection refused")
        response = self.client.post(reverse('candidate_send_otp'), {
            'email': 'alice@candidate.local'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Unable to deliver verification code', data['error'])

        # Undelivered OTP record must be deleted
        self.assertEqual(OTPVerification.objects.filter(candidate=self.candidate).count(), 0)

        # Audit log must record failure
        self.assertTrue(
            ActivityLog.objects.filter(
                candidate=self.candidate,
                activity_type='otp_delivery_failed'
            ).exists()
        )

    def test_send_otp_resend_cooldown(self):
        """Requesting OTP again within cooldown period (60s) is rejected."""
        # First request succeeds
        resp1 = self.client.post(reverse('candidate_send_otp'), {
            'email': 'alice@candidate.local'
        })
        self.assertTrue(resp1.json()['success'])

        # Immediate second request fails with cooldown message
        resp2 = self.client.post(reverse('candidate_send_otp'), {
            'email': 'alice@candidate.local'
        })
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertFalse(data2['success'])
        self.assertIn('Please wait', data2['error'])

    def test_candidate_verify_otp_max_attempts_lockout(self):
        """Exceeding maximum invalid attempts (3) locks out the OTP record."""
        otp_record = OTPVerification(
            candidate=self.candidate,
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        otp_record.set_otp("123456")
        otp_record.save()

        session = self.client.session
        session['otp_email'] = self.candidate.email
        session.save()

        # Attempts 1 and 2
        for i in range(1, 3):
            resp = self.client.post(reverse('candidate_verify_otp'), {'otp': '000000'})
            self.assertFalse(resp.json()['success'])
            self.assertIn('attempt(s) remaining', resp.json()['error'])

        # Attempt 3 reaches limit
        resp3 = self.client.post(reverse('candidate_verify_otp'), {'otp': '000000'})
        self.assertFalse(resp3.json()['success'])
        self.assertIn('Too many invalid attempts', resp3.json()['error'])

        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_used)

        # Attempt 4 after lockout
        resp4 = self.client.post(reverse('candidate_verify_otp'), {'otp': '123456'})
        self.assertFalse(resp4.json()['success'])

    def test_send_otp_invalidates_previous_unused_otps(self):
        """Requesting a new OTP after cooldown marks previous unused OTPs as used."""
        # First OTP
        self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        first_otp = OTPVerification.objects.filter(candidate=self.candidate).first()
        self.assertFalse(first_otp.is_used)

        # Simulate cooldown passage
        first_otp.created_at = timezone.now() - timedelta(seconds=70)
        first_otp.save()

        # Second OTP
        self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        first_otp.refresh_from_db()
        self.assertTrue(first_otp.is_used)

        # New unused OTP exists
        active_otps = OTPVerification.objects.filter(candidate=self.candidate, is_used=False)
        self.assertEqual(active_otps.count(), 1)

    def test_successive_otp_requests_old_code_rejected_new_code_accepted(self):
        """When an OTP is superseded by a newer request, old code is rejected with helpful message and new code succeeds."""
        import re
        mail.outbox.clear()

        # Step 1: Request first OTP
        resp1 = self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        self.assertTrue(resp1.json()['success'])
        self.assertEqual(len(mail.outbox), 1)
        code1 = re.search(r'one-time login code is:\s*(\d{6})', mail.outbox[0].body).group(1)

        # Age the first OTP record so cooldown passes
        first_otp = OTPVerification.objects.filter(candidate=self.candidate).first()
        first_otp.created_at = timezone.now() - timedelta(seconds=65)
        first_otp.save()

        # Step 2: Request second OTP
        resp2 = self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        self.assertTrue(resp2.json()['success'])
        self.assertEqual(len(mail.outbox), 2)
        code2 = re.search(r'one-time login code is:\s*(\d{6})', mail.outbox[1].body).group(1)
        self.assertNotEqual(code1, code2)

        # Step 3: Attempt verification with old (superseded) code1
        verify_resp_old = self.client.post(reverse('candidate_verify_otp'), {'otp': code1})
        self.assertEqual(verify_resp_old.status_code, 200)
        old_data = verify_resp_old.json()
        self.assertFalse(old_data['success'])
        self.assertIn('replaced by a newer OTP request', old_data['error'])

        # Step 4: Verify with current code2 succeeds
        verify_resp_new = self.client.post(reverse('candidate_verify_otp'), {'otp': code2})
        self.assertEqual(verify_resp_new.status_code, 200)
        new_data = verify_resp_new.json()
        self.assertTrue(new_data['success'])
        self.assertEqual(self.client.session.get('user_role'), 'candidate')

    def test_cooldown_enforced_even_if_previous_otp_was_used(self):
        """Cooldown window (60s) applies even if the previous OTP was already verified/used."""
        import re
        mail.outbox.clear()

        # Send and successfully verify OTP
        self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        code = re.search(r'one-time login code is:\s*(\d{6})', mail.outbox[0].body).group(1)
        self.client.post(reverse('candidate_verify_otp'), {'otp': code})

        # OTP is now used
        used_otp = OTPVerification.objects.filter(candidate=self.candidate).first()
        self.assertTrue(used_otp.is_used)

        # Immediate repeat request must be blocked by cooldown
        resp_blocked = self.client.post(reverse('candidate_send_otp'), {'email': 'alice@candidate.local'})
        self.assertFalse(resp_blocked.json()['success'])
        self.assertIn('Please wait', resp_blocked.json()['error'])



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


class ProductionHardeningAndSecurityTests(TestCase):
    """Test suite verifying security hardening, open redirect mitigation, rate-limiting, and error templates."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Security Admin",
            email="secadmin@hirescan.local"
        )
        self.admin.set_password("SecurePass123!")
        self.admin.save()

        self.candidate = Candidate.objects.create(
            name="Security Candidate",
            email="sec.candidate@test.local",
            is_active=True
        )

    def test_admin_login_safe_internal_redirect(self):
        """Valid internal relative URL in next parameter is followed after authentication."""
        response = self.client.post(reverse('admin_login'), {
            'email': 'secadmin@hirescan.local',
            'password': 'SecurePass123!',
            'next': '/admin/candidates/'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/admin/candidates/')

    def test_admin_login_blocks_malicious_open_redirect(self):
        """Malicious external URL in next parameter is rejected, falling back to admin dashboard."""
        response = self.client.post(reverse('admin_login'), {
            'email': 'secadmin@hirescan.local',
            'password': 'SecurePass123!',
            'next': 'https://evil.phishing-site.com/steal-creds'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_dashboard'))

    def test_otp_request_rate_limiting_enforcement(self):
        """Exceeding configured OTP requests per minute from an IP triggers HTTP 429."""
        from django.test import override_settings
        from django.core.cache import cache
        cache.clear()

        with override_settings(ENFORCE_OTP_RATE_LIMIT_IN_TESTS=True, OTP_IP_RATE_LIMIT_PER_MINUTE=2):
            # First request - OK
            resp1 = self.client.post(reverse('candidate_send_otp'), {'email': 'sec.candidate@test.local'})
            self.assertEqual(resp1.status_code, 200)

            # Second request (simulate different candidate so cooldown doesn't fire first)
            cand2 = Candidate.objects.create(name="Cand Two", email="cand2@test.local")
            resp2 = self.client.post(reverse('candidate_send_otp'), {'email': 'cand2@test.local'})
            self.assertEqual(resp2.status_code, 200)

            # Third request exceeds limit (2/min) -> 429 Too Many Requests
            cand3 = Candidate.objects.create(name="Cand Three", email="cand3@test.local")
            resp3 = self.client.post(reverse('candidate_send_otp'), {'email': 'cand3@test.local'})
            self.assertEqual(resp3.status_code, 429)
            self.assertIn('Too many verification code requests', resp3.json()['error'])

        cache.clear()

    def test_custom_404_view_renders_correctly(self):
        """Non-existent URL renders custom 404 page with HireScan branding."""
        response = self.client.get('/definitely-nonexistent-route-404-check/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page Not Found', status_code=404)
        self.assertContains(response, 'Return to Homepage', status_code=404)

    def test_custom_error_handlers(self):
        """Custom 400, 403, and 500 views render expected error status codes and copy."""
        from config.views import error_400, error_403, error_500
        from django.test import RequestFactory
        factory = RequestFactory()

        req400 = factory.get('/')
        res400 = error_400(req400)
        self.assertEqual(res400.status_code, 400)
        self.assertIn(b'Invalid Request', res400.content)

        req403 = factory.get('/')
        res403 = error_403(req403)
        self.assertEqual(res403.status_code, 403)
        self.assertIn(b'Access Restricted', res403.content)

        req500 = factory.get('/')
        res500 = error_500(req500)
        self.assertEqual(res500.status_code, 500)
        self.assertIn(b'Internal Server Error', res500.content)


class AuthenticatedFooterTests(TestCase):
    """Test suite for mentor-requested authenticated footer across both roles."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Footer Test Admin",
            email="footer.admin@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.candidate = Candidate.objects.create(
            name="Footer Test Candidate",
            email="footer.candidate@test.local"
        )

    def test_authenticated_footer_displayed_for_admin(self):
        """Admin portal pages display the exact two-line session footer when authenticated."""
        self.client.post(reverse('admin_login'), {
            'email': 'footer.admin@test.local',
            'password': 'AdminPass123!'
        })
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Check line 1: © 2026 HireScan Test Management Tool. All rights reserved.
        self.assertTrue(
            '2026 HireScan Test Management Tool. All rights reserved.' in content and
            ('&copy;' in content or '©' in content)
        )
        # Check line 2: Secure Session Authentication • Role-Based Access Control
        self.assertTrue(
            'Secure Session Authentication' in content and
            'Role-Based Access Control' in content and
            ('&bull;' in content or '•' in content)
        )

    def test_authenticated_footer_displayed_for_candidate(self):
        """Candidate portal pages display the exact two-line session footer when authenticated."""
        session = self.client.session
        session['candidate_id'] = str(self.candidate.candidate_id)
        session['user_role'] = 'candidate'
        session.save()

        response = self.client.get(reverse('candidate_dashboard'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Check line 1: © 2026 HireScan Test Management Tool. All rights reserved.
        self.assertTrue(
            '2026 HireScan Test Management Tool. All rights reserved.' in content and
            ('&copy;' in content or '©' in content)
        )
        # Check line 2: Secure Session Authentication • Role-Based Access Control
        self.assertTrue(
            'Secure Session Authentication' in content and
            'Role-Based Access Control' in content and
            ('&bull;' in content or '•' in content)
        )

    def test_unauthenticated_page_does_not_display_session_footer(self):
        """Public homepage does not display authenticated session footer component."""
        response = self.client.get(reverse('homepage'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertNotIn('hs-auth-footer', content)


class OTPEmailTemplateTests(TestCase):
    """Test suite for professional responsive HTML OTP email template and fallbacks."""

    def setUp(self):
        self.client = Client()
        self.candidate = Candidate.objects.create(
            name="Email Test Candidate",
            email="otp.recipient@test.local"
        )

    def test_otp_email_contains_html_and_plaintext_alternatives(self):
        """OTP email must deliver both plaintext fallback and professional HTML body."""
        mail.outbox = []
        response = self.client.post(reverse('candidate_send_otp'), {
            'email': 'otp.recipient@test.local'
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.subject, 'HireScan — Your Login OTP')
        self.assertIn('otp.recipient@test.local', email.to)

        # Plaintext fallback checks
        self.assertIn('one-time login code is:', email.body)
        self.assertIn('expires in', email.body)

        # HTML message checks
        self.assertEqual(len(email.alternatives), 1)
        html_body, mimetype = email.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('HireScan', html_body)
        self.assertIn('Verification Code', html_body)
        self.assertIn('Do not share this code with anyone.', html_body)
        self.assertIn('minutes', html_body)


