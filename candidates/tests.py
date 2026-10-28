import io
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Admin, Candidate, ActivityLog
from assessments.models import Test, TestRegistration


class CandidateManagementTests(TestCase):
    """Test suite for candidate roster, detail, edit, and toggle active views."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Admin Tester",
            email="admin.candidate@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        # Login admin session
        self.client.post(reverse('admin_login'), {
            'email': 'admin.candidate@test.local',
            'password': 'AdminPass123!'
        })

        self.candidate = Candidate.objects.create(
            name="John Doe",
            email="john.doe@test.local",
            whatsapp_number="9876543210",
            college_name_address="Apex Tech",
            qualification="B.Tech",
            passing_year=2025,
            is_active=True
        )

    def test_candidate_list_requires_admin_auth(self):
        """Unauthenticated requests to candidate list redirect to admin login."""
        anonymous_client = Client()
        response = anonymous_client.get(reverse('candidate_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin_login'), response.url)

    def test_candidate_list_accessible_when_authenticated(self):
        """Authenticated admins can access candidate list."""
        response = self.client.get(reverse('candidate_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")
        self.assertContains(response, "john.doe@test.local")

    def test_candidate_list_search_by_name_and_email(self):
        """Search query filters candidates by name or email."""
        Candidate.objects.create(
            name="Alice Walker",
            email="alice.walker@test.local"
        )
        # Search by name
        res = self.client.get(reverse('candidate_list') + '?q=Alice')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Alice Walker")
        self.assertNotContains(res, "John Doe")

        # Search by email
        res2 = self.client.get(reverse('candidate_list') + '?q=john.doe')
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, "John Doe")
        self.assertNotContains(res2, "Alice Walker")

    def test_candidate_detail_view(self):
        """Candidate detail shows full profile and registrations."""
        response = self.client.get(reverse('candidate_detail', kwargs={'candidate_id': self.candidate.candidate_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")
        self.assertContains(response, "Apex Tech")
        self.assertContains(response, "9876543210")

    def test_candidate_edit_success(self):
        """Editing candidate details updates the record and logs activity."""
        response = self.client.post(
            reverse('candidate_edit', kwargs={'candidate_id': self.candidate.candidate_id}),
            {
                'name': 'Johnathan Doe',
                'email': 'john.doe.new@test.local',
                'whatsapp_number': '9998887776',
                'college_name_address': 'New Tech College',
                'qualification': 'M.Tech',
                'passing_year': '2026',
                'other_details': 'Senior Architect',
                'is_active': 'on'
            }
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.name, 'Johnathan Doe')
        self.assertEqual(self.candidate.email, 'john.doe.new@test.local')
        self.assertEqual(self.candidate.passing_year, 2026)
        self.assertTrue(self.candidate.is_active)

    def test_candidate_edit_duplicate_email_rejected(self):
        """Cannot update a candidate email to match an existing candidate's email."""
        Candidate.objects.create(
            name="Other Person",
            email="other@test.local"
        )
        response = self.client.post(
            reverse('candidate_edit', kwargs={'candidate_id': self.candidate.candidate_id}),
            {
                'name': 'John Doe',
                'email': 'other@test.local',  # duplicate!
                'whatsapp_number': '9876543210',
                'passing_year': '2025',
                'is_active': 'on'
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_candidate_toggle_active(self):
        """Toggling active status deactivates then reactivates candidate."""
        # Deactivate
        res = self.client.post(reverse('candidate_toggle_active', kwargs={'candidate_id': self.candidate.candidate_id}))
        self.assertEqual(res.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.is_active)

        # Reactivate
        res2 = self.client.post(reverse('candidate_toggle_active', kwargs={'candidate_id': self.candidate.candidate_id}))
        self.assertEqual(res2.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.is_active)


class CandidateCSVImportTests(TestCase):
    """Test suite for candidate CSV roster upload, validation, duplicate handling, and reporting."""

    def setUp(self):
        self.client = Client()
        self.admin = Admin(
            name="Admin Import",
            email="admin.import@test.local"
        )
        self.admin.set_password("AdminPass123!")
        self.admin.save()

        self.client.post(reverse('admin_login'), {
            'email': 'admin.import@test.local',
            'password': 'AdminPass123!'
        })

        self.test = Test.objects.create(
            test_name="Python Backend Assessment",
            duration_minutes=30,
            total_questions=10,
            passing_marks=6,
            is_active=False
        )

    def test_candidate_csv_template_download(self):
        """Downloading template returns text/csv with correct column headers."""
        response = self.client.get(reverse('candidate_template_download'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('email,name,whatsapp_number,college_name_address,qualification,passing_year,other', content)

    def test_candidate_import_valid_csv(self):
        """Importing valid CSV creates candidate records and test registrations."""
        csv_data = (
            "email,name,whatsapp_number,college_name_address,qualification,passing_year,other\n"
            "robert@test.local,Robert Frost,9876543210,Harvard,B.Sc,2024,Developer\n"
            "emily@test.local,Emily Dickinson,9876543211,Amherst,M.A,2025,Writer\n"
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'candidates.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)

        # Verify candidate records created
        self.assertTrue(Candidate.objects.filter(email='robert@test.local').exists())
        self.assertTrue(Candidate.objects.filter(email='emily@test.local').exists())

        # Verify test registrations created
        c1 = Candidate.objects.get(email='robert@test.local')
        c2 = Candidate.objects.get(email='emily@test.local')
        self.assertTrue(TestRegistration.objects.filter(candidate=c1, test=self.test).exists())
        self.assertTrue(TestRegistration.objects.filter(candidate=c2, test=self.test).exists())

    def test_candidate_import_missing_required_headers(self):
        """CSV missing 'email' or 'name' header is rejected."""
        csv_data = (
            "user_email,full_name,phone\n"
            "user@test.local,User One,123456\n"
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'invalid_headers.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Missing required headers')

    def test_candidate_import_invalid_email_and_missing_name(self):
        """Rows with invalid email or missing name are rejected and reported."""
        csv_data = (
            "email,name,whatsapp_number,passing_year\n"
            "not-an-email,Bad Email User,123456,2025\n"
            "valid@test.local,,123456,2025\n"  # missing name
            "good@test.local,Good User,123456,2025\n"
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'validation_test.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email format')
        self.assertContains(response, 'Name is missing')

        # Good user created
        self.assertTrue(Candidate.objects.filter(email='good@test.local').exists())
        # Bad users not created
        self.assertFalse(Candidate.objects.filter(email='not-an-email').exists())

    def test_candidate_import_in_file_duplicate_detection(self):
        """Duplicate emails within the uploaded file are caught and reported."""
        csv_data = (
            "email,name,whatsapp_number\n"
            "dup@test.local,User First,123\n"
            "dup@test.local,User Second,456\n"  # in-file duplicate!
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'duplicate_file.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Duplicate email')

    def test_candidate_import_reuses_existing_candidate_and_skips_duplicate_registration(self):
        """
        If a candidate already exists in the database, reuse their record without creating
        a duplicate candidate, and skip duplicate test registration if already registered.
        """
        # Pre-create candidate
        existing_cand = Candidate.objects.create(
            name="Existing Jane",
            email="jane.existing@test.local"
        )
        # Pre-register for this test
        TestRegistration.objects.create(candidate=existing_cand, test=self.test)

        csv_data = (
            "email,name,whatsapp_number\n"
            "jane.existing@test.local,Jane With New Details,9999999999\n"
        )
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'existing.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)

        # Still only 1 candidate record with this email
        self.assertEqual(Candidate.objects.filter(email='jane.existing@test.local').count(), 1)
        # Original name preserved (not silently overwritten)
        existing_cand.refresh_from_db()
        self.assertEqual(existing_cand.name, "Existing Jane")
        # Still only 1 registration for this test
        self.assertEqual(TestRegistration.objects.filter(candidate=existing_cand, test=self.test).count(), 1)

    def test_candidate_registered_for_multiple_different_tests(self):
        """The same candidate can register for multiple different tests."""
        test2 = Test.objects.create(
            test_name="Second Assessment",
            duration_minutes=45,
            total_questions=15,
            passing_marks=8,
            is_active=False
        )

        cand = Candidate.objects.create(
            name="Multi Test Candidate",
            email="multi@test.local"
        )

        # Import into test 1
        csv1 = io.BytesIO(b"email,name\nmulti@test.local,Multi Test Candidate\n")
        csv1.name = "t1.csv"
        self.client.post(reverse('candidate_import'), {'test_id': str(self.test.test_id), 'csv_file': csv1})

        # Import into test 2
        csv2 = io.BytesIO(b"email,name\nmulti@test.local,Multi Test Candidate\n")
        csv2.name = "t2.csv"
        self.client.post(reverse('candidate_import'), {'test_id': str(test2.test_id), 'csv_file': csv2})

        self.assertTrue(TestRegistration.objects.filter(candidate=cand, test=self.test).exists())
        self.assertTrue(TestRegistration.objects.filter(candidate=cand, test=test2).exists())

    def test_download_candidate_import_errors_csv(self):
        """Failed rows can be downloaded as an error report CSV."""
        csv_data = "email,name\nbad-email,Bad User\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'fail.csv'

        self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })

        # Download error CSV
        response = self.client.get(reverse('candidate_import_error_csv'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('row_number,email,name,error_reason', content)
        self.assertIn('bad-email', content)

    def test_download_candidate_import_errors_csv_formula_injection_defense(self):
        """Formula injection attempts in invalid CSV rows are sanitized with single quotes."""
        csv_data = "email,name\n=calc|A0!0,=@SUM(1;2)\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'injection.csv'

        self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })

        response = self.client.get(reverse('candidate_import_error_csv'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Leading '=' must be prefixed with single quote
        self.assertIn("'=calc|a0!0", content)
        self.assertIn("'=@SUM(1;2)", content)

    def test_candidate_import_empty_file_rejected(self):
        """Completely empty file (0 bytes) is rejected with clear error message."""
        csv_file = io.BytesIO(b"")
        csv_file.name = 'empty.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The uploaded CSV file is empty.')

    def test_candidate_import_whitespace_only_file_rejected(self):
        """File with only whitespace and empty lines is rejected as empty."""
        csv_file = io.BytesIO(b"   \n\n\r\n   ")
        csv_file.name = 'whitespace.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The uploaded CSV file is empty.')

    def test_candidate_import_header_only_file_warns_no_data(self):
        """CSV file with valid headers but no candidate data rows displays clear warning."""
        csv_data = "email,name\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'header_only.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'contains headers but no candidate data rows')

    def test_candidate_import_utf8_bom_and_casing_and_spaces_handled(self):
        """Headers with UTF-8 BOM, casing variations, and extra whitespace parse successfully."""
        # \ufeff is UTF-8 BOM
        csv_data = "\ufeff  EMAIL  ,  Name  \nCandidate.BOM@test.local,Bom User\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'bom_test.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Candidate.objects.filter(email='candidate.bom@test.local').exists())

    def test_candidate_import_malformed_row_missing_columns(self):
        """Malformed row missing required columns is rejected with row-level error without crash."""
        csv_data = "email,name\nonlyonevalue_no_comma\nvalid.after@test.local,Valid User\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'malformed.csv'

        response = self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })
        self.assertEqual(response.status_code, 200)
        # Valid user was still created
        self.assertTrue(Candidate.objects.filter(email='valid.after@test.local').exists())
        # Error report contains malformed row reason
        self.assertContains(response, 'Row is missing')

    def test_candidate_import_triggers_registration_notification(self):
        """Importing a new candidate creates a registration and logs a registration notification."""
        from assessments.models import NotificationLog
        from django.core import mail
        mail.outbox.clear()

        csv_data = "email,name\nnew.notif.candidate@test.local,Notification Cand\n"
        csv_file = io.BytesIO(csv_data.encode('utf-8'))
        csv_file.name = 'cand_notif.csv'

        self.client.post(reverse('candidate_import'), {
            'test_id': str(self.test.test_id),
            'csv_file': csv_file
        })

        cand = Candidate.objects.filter(email='new.notif.candidate@test.local').first()
        self.assertIsNotNone(cand)
        self.assertTrue(NotificationLog.objects.filter(
            candidate=cand,
            test=self.test,
            notification_type='registered'
        ).exists())

