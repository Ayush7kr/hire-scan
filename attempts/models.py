import uuid
from django.db import models
from assessments.models import TestRegistration, Question


class TestAttempt(models.Model):
    """A single test attempt by a candidate."""
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    ]

    attempt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.OneToOneField(
        TestRegistration, on_delete=models.CASCADE, related_name='attempt',
        help_text='Ensures at most one attempt per registration'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    total_questions = models.IntegerField(default=0)
    correct_answers = models.IntegerField(default=0)
    incorrect_answers = models.IntegerField(default=0)
    unanswered = models.IntegerField(default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_passed = models.BooleanField(null=True, blank=True)
    time_taken_seconds = models.IntegerField(null=True, blank=True)
    submission_reason = models.CharField(max_length=50, blank=True, default='')  # 'manual', 'timeout'

    class Meta:
        db_table = 'test_attempt'
        indexes = [
            models.Index(fields=['status'], name='idx_attempt_status'),
            models.Index(fields=['registration'], name='idx_attempt_registration'),
        ]

    def __str__(self):
        return f"Attempt by {self.registration.candidate.name} for {self.registration.test.test_name}"

    @property
    def deadline(self):
        """Authoritative server-side deadline based on start_time and test duration."""
        from datetime import timedelta
        return self.start_time + timedelta(minutes=self.registration.test.duration_minutes)

    @property
    def is_expired(self):
        """Check whether the attempt time limit has elapsed on the server."""
        from django.utils import timezone
        return timezone.now() > self.deadline

    @property
    def remaining_seconds(self):
        """Calculate remaining time in seconds from server timestamp."""
        from django.utils import timezone
        diff = (self.deadline - timezone.now()).total_seconds()
        return max(0, int(diff))


class AttemptQuestion(models.Model):
    """Individual question assigned to a test attempt with the candidate's response."""
    aq_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        TestAttempt, on_delete=models.CASCADE, related_name='attempt_questions'
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name='attempt_records'
    )
    question_order = models.IntegerField(help_text='Order of this question in the attempt')
    selected_option = models.IntegerField(
        null=True, blank=True,
        choices=[(1, 'Option 1'), (2, 'Option 2'), (3, 'Option 3'), (4, 'Option 4')],
        help_text='The option the candidate selected (null if unanswered)'
    )
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'attempt_question'
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'question'],
                name='unique_attempt_question'
            ),
        ]
        indexes = [
            models.Index(fields=['attempt', 'question_order'], name='idx_aq_attempt_order'),
        ]
        ordering = ['question_order']

    def __str__(self):
        return f"Q{self.question_order} in {self.attempt}"

