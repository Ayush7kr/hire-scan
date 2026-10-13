import uuid
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


class Admin(models.Model):
    """System administrator / evaluator account."""
    admin_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admin'
        indexes = [
            models.Index(fields=['email'], name='idx_admin_email'),
        ]

    def __str__(self):
        return f"{self.name} ({self.email})"

    def set_password(self, raw_password):
        """Hash and store password using Django's password hashers."""
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        """Verify password against stored hash."""
        return check_password(raw_password, self.password_hash)


class Candidate(models.Model):
    """Job applicant / examinee record. Created via admin CSV import."""
    candidate_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(max_length=255, unique=True)
    whatsapp_number = models.CharField(max_length=20, blank=True, default='')
    college_name_address = models.TextField(blank=True, default='')
    qualification = models.CharField(max_length=100, blank=True, default='')
    passing_year = models.IntegerField(null=True, blank=True)
    other_details = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'candidate'
        indexes = [
            models.Index(fields=['email'], name='idx_candidate_email'),
        ]

    def __str__(self):
        return f"{self.name} ({self.email})"


class OTPVerification(models.Model):
    """One-time password records for candidate authentication."""
    otp_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name='otp_records'
    )
    otp_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0)

    class Meta:
        db_table = 'otp_verification'
        indexes = [
            models.Index(fields=['candidate', 'is_used'], name='idx_otp_candidate_used'),
            models.Index(fields=['expires_at'], name='idx_otp_expiry'),
        ]

    def __str__(self):
        return f"OTP for {self.candidate.email} (used={self.is_used})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def set_otp(self, raw_otp):
        """Hash and store the OTP."""
        self.otp_hash = make_password(str(raw_otp))

    def check_otp(self, raw_otp):
        """Verify OTP against stored hash."""
        return check_password(str(raw_otp), self.otp_hash)


class ActivityLog(models.Model):
    """Audit trail for authentication, admin, and test activities."""
    activity_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity_logs'
    )
    admin = models.ForeignKey(
        Admin, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity_logs'
    )
    # attempt FK will reference attempts.TestAttempt — use string reference
    attempt = models.ForeignKey(
        'attempts.TestAttempt', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity_logs'
    )
    activity_type = models.CharField(max_length=100)
    activity_details = models.TextField(blank=True, default='')
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_log'
        indexes = [
            models.Index(fields=['activity_type'], name='idx_activity_type'),
            models.Index(fields=['occurred_at'], name='idx_activity_occurred'),
        ]
        ordering = ['-occurred_at']

    def __str__(self):
        return f"{self.activity_type} at {self.occurred_at}"
