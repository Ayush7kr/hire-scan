"""
Assessment Engine Services for HireScan.

Handles candidate test eligibility, transactional attempt creation with
randomized question assignment, server-authoritative timer evaluation,
scoring, topic-wise performance aggregation, and activity logging.
"""
import random
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from accounts.models import ActivityLog
from assessments.models import TestRegistration, Question
from attempts.models import TestAttempt, AttemptQuestion


def validate_candidate_eligibility(candidate, registration):
    """
    Validate that candidate is eligible to access/start the specified test registration.
    Returns (is_eligible: bool, reason: str).
    """
    if not candidate or not candidate.is_active:
        return False, "Candidate account is inactive or not found."

    if registration.candidate_id != candidate.candidate_id:
        return False, "This test registration does not belong to you."

    if registration.status != 'registered':
        return False, f"Registration status is '{registration.status}' and cannot be accessed."

    test = registration.test
    if not test.is_active:
        return False, "This assessment is currently inactive and unavailable."

    available_questions = test.questions.count()
    if available_questions < test.total_questions:
        return False, (
            f"Assessment question bank does not have enough questions "
            f"({available_questions} available, {test.total_questions} required)."
        )

    # Check if attempt already exists and is finalized
    try:
        attempt = registration.attempt
        if attempt.status in ['completed', 'expired']:
            return False, "You have already completed this assessment. Retakes are not permitted."
    except TestRegistration.attempt.RelatedObjectDoesNotExist:
        pass

    return True, ""


def start_attempt_for_registration(registration):
    """
    Transactionally create or retrieve an in-progress TestAttempt.
    Enforces one-attempt-per-registration constraint, selects randomized questions,
    and assigns a fixed question ordering (1..N).
    """
    with transaction.atomic():
        # Lock registration record to prevent concurrent attempts from double-clicks
        locked_reg = TestRegistration.objects.select_for_update().get(
            registration_id=registration.registration_id
        )

        # Re-check if an attempt already exists
        existing_attempt = TestAttempt.objects.filter(registration=locked_reg).first()
        if existing_attempt:
            # If expired, finalize it right away
            if existing_attempt.status == 'in_progress' and existing_attempt.is_expired:
                evaluate_attempt(existing_attempt, submission_reason='timeout')
            return existing_attempt

        test = locked_reg.test
        all_question_ids = list(test.questions.values_list('question_id', flat=True))

        if len(all_question_ids) < test.total_questions:
            raise ValueError(
                f"Question bank has {len(all_question_ids)} questions; "
                f"{test.total_questions} required."
            )

        # Randomly sample the configured number of questions (only once upon attempt creation)
        selected_question_ids = random.sample(all_question_ids, test.total_questions)

        # Create TestAttempt record
        attempt = TestAttempt.objects.create(
            registration=locked_reg,
            status='in_progress',
            total_questions=test.total_questions,
            start_time=timezone.now(),
        )

        # Create AttemptQuestion records with stable question_order 1..N
        attempt_questions = [
            AttemptQuestion(
                attempt=attempt,
                question_id=qid,
                question_order=order,
                selected_option=None,
            )
            for order, qid in enumerate(selected_question_ids, start=1)
        ]
        AttemptQuestion.objects.bulk_create(attempt_questions)

        # Audit log attempt creation
        ActivityLog.objects.create(
            candidate=locked_reg.candidate,
            attempt=attempt,
            activity_type='ATTEMPT_STARTED',
            activity_details=(
                f"Started assessment '{test.test_name}' "
                f"({test.total_questions} questions, {test.duration_minutes} mins limit)."
            ),
        )

        return attempt


def evaluate_attempt(attempt, submission_reason='manual'):
    """
    Authoritative server-side evaluation of a TestAttempt.
    Computes correct, incorrect, unanswered, score, percentage, pass status,
    and duration. Idempotent: once finalized, returns existing results.
    """
    with transaction.atomic():
        locked_attempt = TestAttempt.objects.select_for_update().get(
            attempt_id=attempt.attempt_id
        )

        # Idempotency check: if already completed or expired, do not re-calculate
        if locked_attempt.status in ['completed', 'expired']:
            return locked_attempt

        test = locked_attempt.registration.test
        now = timezone.now()

        # If submission is due to timeout or past deadline, cap end_time at deadline
        deadline = locked_attempt.deadline
        if submission_reason == 'timeout' or now > deadline:
            final_status = 'expired'
            submission_reason = 'timeout'
            end_time = min(now, deadline + timedelta(seconds=5))
        else:
            final_status = 'completed'
            end_time = now

        # Retrieve all assigned attempt questions with their authoritative questions
        attempt_questions = list(
            locked_attempt.attempt_questions.select_related('question').order_by('question_order')
        )

        total_questions = len(attempt_questions)
        correct_count = 0
        incorrect_count = 0
        unanswered_count = 0

        # Evaluate each question against Question.correct_option
        for aq in attempt_questions:
            selected = aq.selected_option
            correct = aq.question.correct_option

            if selected is None:
                aq.is_correct = False
                unanswered_count += 1
            elif selected == correct:
                aq.is_correct = True
                correct_count += 1
            else:
                aq.is_correct = False
                incorrect_count += 1

        # Bulk update is_correct on AttemptQuestion records
        AttemptQuestion.objects.bulk_update(attempt_questions, ['is_correct'])

        # Scoring: 1 mark per correct answer, 0 for incorrect/unanswered (no negative marking)
        score = correct_count
        percentage = (
            Decimal(str(round((score / total_questions) * 100, 2)))
            if total_questions > 0
            else Decimal('0.00')
        )
        is_passed = score >= test.passing_marks

        # Calculate time taken in seconds
        time_taken_seconds = max(0, int((end_time - locked_attempt.start_time).total_seconds()))

        # Update and persist attempt
        locked_attempt.status = final_status
        locked_attempt.submission_reason = submission_reason
        locked_attempt.end_time = end_time
        locked_attempt.score = score
        locked_attempt.total_questions = total_questions
        locked_attempt.correct_answers = correct_count
        locked_attempt.incorrect_answers = incorrect_count
        locked_attempt.unanswered = unanswered_count
        locked_attempt.percentage = percentage
        locked_attempt.is_passed = is_passed
        locked_attempt.time_taken_seconds = time_taken_seconds
        locked_attempt.save()

        # Audit log attempt finalization
        ActivityLog.objects.create(
            candidate=locked_attempt.registration.candidate,
            attempt=locked_attempt,
            activity_type='ATTEMPT_SUBMITTED' if final_status == 'completed' else 'ATTEMPT_TIMED_OUT',
            activity_details=(
                f"Assessment '{test.test_name}' finalized ({submission_reason}). "
                f"Score: {score}/{total_questions} ({percentage}%), Passed: {is_passed}."
            ),
        )

        return locked_attempt


def get_topic_performance(attempt):
    """
    Aggregate topic-wise performance for an evaluated attempt.
    Returns a list of dicts with topic metrics and improvement suggestions.
    """
    attempt_questions = (
        attempt.attempt_questions
        .select_related('question')
        .order_by('question_order')
    )

    topics_map = {}
    for aq in attempt_questions:
        q = aq.question
        topic = q.topic or 'General'

        if topic not in topics_map:
            topics_map[topic] = {
                'topic': topic,
                'total': 0,
                'correct': 0,
                'incorrect': 0,
                'unanswered': 0,
                'suggestions': set(),
            }

        topics_map[topic]['total'] += 1
        if aq.is_correct:
            topics_map[topic]['correct'] += 1
        elif aq.selected_option is None:
            topics_map[topic]['unanswered'] += 1
            if q.suggestions:
                topics_map[topic]['suggestions'].add(q.suggestions.strip())
        else:
            topics_map[topic]['incorrect'] += 1
            if q.suggestions:
                topics_map[topic]['suggestions'].add(q.suggestions.strip())

    topic_results = []
    for topic_data in topics_map.values():
        total = topic_data['total']
        correct = topic_data['correct']
        accuracy = round((correct / total) * 100, 1) if total > 0 else 0.0

        if accuracy >= 75.0:
            level = 'Proficient'
            badge_class = 'bg-success-subtle text-success border border-success-subtle'
        elif accuracy >= 50.0:
            level = 'Average'
            badge_class = 'bg-warning-subtle text-warning border border-warning-subtle'
        else:
            level = 'Needs Work'
            badge_class = 'bg-danger-subtle text-danger border border-danger-subtle'

        topic_results.append({
            'topic': topic_data['topic'],
            'total': total,
            'correct': correct,
            'incorrect': topic_data['incorrect'],
            'unanswered': topic_data['unanswered'],
            'accuracy': accuracy,
            'level': level,
            'badge_class': badge_class,
            'suggestions': sorted(list(topic_data['suggestions'])),
        })

    topic_results.sort(key=lambda t: t['accuracy'])
    return topic_results
