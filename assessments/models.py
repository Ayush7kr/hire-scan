import uuid
from django.db import models
from accounts.models import Candidate


class Test(models.Model):
    """Assessment / examination configuration."""
    test_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    duration_minutes = models.PositiveIntegerField(help_text='Test duration in minutes')
    total_questions = models.PositiveIntegerField(
        help_text='Number of questions presented to each candidate'
    )
    passing_marks = models.PositiveIntegerField(help_text='Minimum marks to pass')
    is_active = models.BooleanField(default=False)
    start_time = models.DateTimeField(null=True, blank=True, help_text='Scheduled start time for the test window')
    end_time = models.DateTimeField(null=True, blank=True, help_text='Scheduled end time for the test window')
    is_cancelled = models.BooleanField(default=False, help_text='Indicates whether the test has been cancelled')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'test'
        indexes = [
            models.Index(fields=['is_active'], name='idx_test_active'),
            models.Index(fields=['is_cancelled'], name='idx_test_cancelled'),
            models.Index(fields=['start_time'], name='idx_test_start_time'),
        ]

    def __str__(self):
        return f"{self.test_name} ({self.status_display})"

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def status(self):
        """
        Derives the overall test status among:
        - 'cancelled': Explicitly marked as cancelled by an administrator.
        - 'completed': The scheduled end time has elapsed, or all registered candidates have completed their attempts and test is closed.
        - 'in_progress': Currently active and within the permitted time window (start_time <= now <= end_time).
        - 'upcoming': Active/published with a scheduled future start time (now < start_time).
        - 'scheduled': Configured/drafted with a schedule or pending publication (is_active=False).
        """
        from django.utils import timezone
        now = timezone.now()

        # 1. Cancelled always takes precedence
        if self.is_cancelled:
            return 'cancelled'

        # 2. Window-based completion
        if self.end_time and now > self.end_time:
            return 'completed'

        # 3. Candidate-based completion: if test has registrations and all are completed/expired,
        # and test is either inactive or window has ended
        reg_count = self.registrations.filter(status='registered').count()
        if reg_count > 0:
            from attempts.models import TestAttempt
            completed_attempts = TestAttempt.objects.filter(
                registration__test=self,
                registration__status='registered',
                status__in=['completed', 'expired']
            ).count()
            if completed_attempts == reg_count:
                if not self.is_active or (self.end_time and now >= self.end_time):
                    return 'completed'

        # 4. Schedule-based statuses
        if self.start_time:
            if now < self.start_time:
                # Future start time
                return 'upcoming' if self.is_active else 'scheduled'
            else:
                # now >= self.start_time
                if self.end_time and now > self.end_time:
                    return 'completed'
                if self.is_active:
                    return 'in_progress'
                # Inactive after start_time
                from attempts.models import TestAttempt
                if TestAttempt.objects.filter(registration__test=self, status__in=['completed', 'expired']).exists():
                    return 'completed'
                return 'scheduled'

        # 5. Default when no explicit start_time is set
        if self.is_active:
            return 'in_progress'

        # Inactive without start_time: check if it already ran and completed
        from attempts.models import TestAttempt
        if (
            TestAttempt.objects.filter(registration__test=self, status__in=['completed', 'expired']).exists()
            and not TestAttempt.objects.filter(registration__test=self, status='in_progress').exists()
        ):
            return 'completed'

        return 'scheduled'

    @property
    def status_display(self):
        mapping = {
            'cancelled': 'Cancelled',
            'completed': 'Completed',
            'in_progress': 'In Progress',
            'upcoming': 'Upcoming',
            'scheduled': 'Scheduled',
        }
        return mapping.get(self.status, 'Scheduled')

    @property
    def status_badge_class(self):
        mapping = {
            'cancelled': 'bg-danger-subtle text-danger border border-danger-subtle',
            'completed': 'bg-primary-subtle text-primary border border-primary-subtle',
            'in_progress': 'bg-success-subtle text-success border border-success-subtle',
            'upcoming': 'bg-info-subtle text-info border border-info-subtle',
            'scheduled': 'bg-secondary-subtle text-secondary border border-secondary-subtle',
        }
        return mapping.get(self.status, 'bg-secondary-subtle text-secondary border')


class Question(models.Model):
    """Question in a test's question bank."""
    question_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    option1 = models.CharField(max_length=500)
    option2 = models.CharField(max_length=500)
    option3 = models.CharField(max_length=500)
    option4 = models.CharField(max_length=500)
    correct_option = models.IntegerField(
        choices=[(1, 'Option 1'), (2, 'Option 2'), (3, 'Option 3'), (4, 'Option 4')],
        help_text='The correct option number (1-4)'
    )
    topic = models.CharField(max_length=100)
    difficulty = models.CharField(
        max_length=20,
        choices=[('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
        default='medium',
        blank=True
    )
    suggestions = models.TextField(blank=True, default='', help_text='Improvement suggestions for this topic')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'question'
        indexes = [
            models.Index(fields=['test', 'topic'], name='idx_question_test_topic'),
        ]

    def __str__(self):
        return f"Q: {self.question_text[:60]}..."

    def get_correct_answer_text(self):
        """Return the text of the correct option."""
        return getattr(self, f'option{self.correct_option}')


class TestRegistration(models.Model):
    """Links a candidate to a test they are eligible to take."""
    registration_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name='registrations'
    )
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name='registrations')
    status = models.CharField(
        max_length=20,
        choices=[('registered', 'Registered'), ('cancelled', 'Cancelled')],
        default='registered'
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'test_registration'
        constraints = [
            models.UniqueConstraint(
                fields=['candidate', 'test'],
                name='unique_candidate_test_registration'
            ),
        ]
        indexes = [
            models.Index(fields=['candidate', 'test'], name='idx_reg_candidate_test'),
        ]

    def __str__(self):
        return f"{self.candidate.name} → {self.test.test_name}"


class NotificationLog(models.Model):
    """
    Log of email notifications and reminders dispatched to candidates.
    Prevents duplicate dispatches and provides auditability for delivery attempts.
    """
    TYPE_CHOICES = [
        ('registered', 'Registration Confirmation'),
        ('available', 'Assessment Available'),
        ('reminder', 'Upcoming Assessment Reminder'),
        ('schedule_updated', 'Schedule Updated'),
        ('cancelled', 'Assessment Cancelled'),
    ]
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name='assessment_notifications'
    )
    test = models.ForeignKey(
        Test, on_delete=models.CASCADE, related_name='notifications'
    )
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    recipient_email = models.EmailField(max_length=255)
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent')
    error_message = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification_log'
        indexes = [
            models.Index(fields=['candidate', 'test', 'notification_type'], name='idx_notif_cand_test_type'),
            models.Index(fields=['sent_at'], name='idx_notif_sent_at'),
            models.Index(fields=['status'], name='idx_notif_status'),
        ]
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.notification_type} to {self.recipient_email} for {self.test.test_name} ({self.status})"

