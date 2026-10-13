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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'test'
        indexes = [
            models.Index(fields=['is_active'], name='idx_test_active'),
        ]

    def __str__(self):
        status = 'Active' if self.is_active else 'Inactive'
        return f"{self.test_name} ({status})"

    @property
    def question_count(self):
        return self.questions.count()


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
