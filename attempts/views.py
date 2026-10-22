"""
Test attempt and candidate assessment views.
"""
import json
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import candidate_required
from accounts.models import Candidate, Admin
from assessments.models import TestRegistration, Question
from attempts.models import TestAttempt, AttemptQuestion
from attempts.services import (
    validate_candidate_eligibility,
    start_attempt_for_registration,
    evaluate_attempt,
    get_topic_performance,
)


@candidate_required
def candidate_dashboard(request):
    """Candidate dashboard — shows assigned tests and their status."""
    candidate = request.candidate_user

    # Get all registrations with related test and attempt data
    registrations = TestRegistration.objects.filter(
        candidate=candidate
    ).select_related('test').prefetch_related('attempt').order_by('-registered_at')

    tests = []
    for reg in registrations:
        attempt = None
        try:
            attempt = reg.attempt
            # If attempt is in progress but expired, finalize it automatically
            if attempt.status == 'in_progress' and attempt.is_expired:
                attempt = evaluate_attempt(attempt, submission_reason='timeout')
        except TestRegistration.attempt.RelatedObjectDoesNotExist:
            attempt = None

        now = timezone.now()
        is_window_open = (
            (not reg.test.start_time or now >= reg.test.start_time) and
            (not reg.test.end_time or now <= reg.test.end_time)
        )
        can_start = (
            reg.status == 'registered'
            and reg.test.is_active
            and not reg.test.is_cancelled
            and is_window_open
            and attempt is None
            and reg.test.questions.count() >= reg.test.total_questions
            and reg.test.status == 'in_progress'
        )
        can_resume = (
            attempt is not None
            and attempt.status == 'in_progress'
            and not attempt.is_expired
        )
        is_completed = (
            attempt is not None
            and attempt.status in ['completed', 'expired']
        )

        tests.append({
            'registration': reg,
            'test': reg.test,
            'attempt': attempt,
            'can_start': can_start,
            'can_resume': can_resume,
            'is_completed': is_completed,
        })

    context = {
        'candidate': candidate,
        'tests': tests,
    }
    return render(request, 'candidate_portal/dashboard.html', context)


@candidate_required
def test_instructions(request, registration_id):
    """
    Test instructions page shown before starting an assessment.
    Validates candidate ownership, test activity, and eligibility.
    """
    registration = get_object_or_404(
        TestRegistration.objects.select_related('test', 'candidate'),
        registration_id=registration_id
    )

    if registration.candidate_id != request.candidate_user.candidate_id:
        return HttpResponseForbidden("You are not authorized to view this registration.")

    # Check if attempt already exists
    try:
        attempt = registration.attempt
        if attempt.status in ['completed', 'expired']:
            messages.info(request, "You have already completed this assessment.")
            return redirect('test_results', attempt_id=attempt.attempt_id)
        elif attempt.status == 'in_progress':
            if attempt.is_expired:
                evaluate_attempt(attempt, submission_reason='timeout')
                return redirect('test_results', attempt_id=attempt.attempt_id)
            messages.info(request, "You have an assessment in progress. Resuming...")
            return redirect('test_take', attempt_id=attempt.attempt_id)
    except TestRegistration.attempt.RelatedObjectDoesNotExist:
        pass

    # Server-side eligibility check
    is_eligible, reason = validate_candidate_eligibility(request.candidate_user, registration)
    if not is_eligible:
        messages.error(request, reason)
        return redirect('candidate_dashboard')

    context = {
        'registration': registration,
        'test': registration.test,
        'candidate': request.candidate_user,
    }
    return render(request, 'candidate_portal/instructions.html', context)


@candidate_required
@require_http_methods(["POST"])
def test_start(request, registration_id):
    """
    Create or resume a TestAttempt for the candidate and registration.
    Uses CSRF-protected POST and atomic transaction to prevent double-starts.
    """
    registration = get_object_or_404(
        TestRegistration.objects.select_related('test', 'candidate'),
        registration_id=registration_id
    )

    if registration.candidate_id != request.candidate_user.candidate_id:
        return HttpResponseForbidden("You are not authorized to start this registration.")

    # Check if attempt already exists
    try:
        attempt = registration.attempt
        if attempt.status in ['completed', 'expired']:
            messages.info(request, "You have already submitted this assessment.")
            return redirect('test_results', attempt_id=attempt.attempt_id)
        elif attempt.status == 'in_progress':
            if attempt.is_expired:
                evaluate_attempt(attempt, submission_reason='timeout')
                return redirect('test_results', attempt_id=attempt.attempt_id)
            return redirect('test_take', attempt_id=attempt.attempt_id)
    except TestRegistration.attempt.RelatedObjectDoesNotExist:
        pass

    # Verify eligibility
    is_eligible, reason = validate_candidate_eligibility(request.candidate_user, registration)
    if not is_eligible:
        messages.error(request, reason)
        return redirect('candidate_dashboard')

    try:
        attempt = start_attempt_for_registration(registration)
        return redirect('test_take', attempt_id=attempt.attempt_id)
    except Exception as e:
        messages.error(request, f"Unable to start assessment: {str(e)}")
        return redirect('test_instructions', registration_id=registration.registration_id)


@candidate_required
def test_take(request, attempt_id):
    """
    Assessment interface with question navigation, countdown timer,
    palette, and autosave.
    """
    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__test', 'registration__candidate'),
        attempt_id=attempt_id
    )

    if attempt.registration.candidate_id != request.candidate_user.candidate_id:
        return HttpResponseForbidden("You are not authorized to access this test attempt.")

    # If already finalized, redirect to results
    if attempt.status in ['completed', 'expired']:
        return redirect('test_results', attempt_id=attempt.attempt_id)

    # If server deadline has passed, finalize immediately
    if attempt.is_expired:
        evaluate_attempt(attempt, submission_reason='timeout')
        messages.warning(request, "Assessment time has expired. Your test has been submitted automatically.")
        return redirect('test_results', attempt_id=attempt.attempt_id)

    # Retrieve all assigned attempt questions in stable order
    attempt_questions = list(
        attempt.attempt_questions
        .select_related('question')
        .order_by('question_order')
    )

    answered_count = sum(1 for aq in attempt_questions if aq.selected_option is not None)
    unanswered_count = attempt.total_questions - answered_count

    context = {
        'attempt': attempt,
        'test': attempt.registration.test,
        'attempt_questions': attempt_questions,
        'answered_count': answered_count,
        'unanswered_count': unanswered_count,
        'remaining_seconds': attempt.remaining_seconds,
        'deadline_iso': attempt.deadline.isoformat(),
        'candidate': request.candidate_user,
    }
    return render(request, 'candidate_portal/test_interface.html', context)


@candidate_required
@require_http_methods(["POST"])
def test_autosave(request, attempt_id):
    """
    Authenticated AJAX endpoint for saving answers.
    Validates attempt ownership, active status, and deadline.
    Returns structured JSON with save state and remaining seconds.
    """
    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__candidate', 'registration__test'),
        attempt_id=attempt_id
    )

    if attempt.registration.candidate_id != request.candidate_user.candidate_id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    if attempt.status in ['completed', 'expired']:
        return JsonResponse({
            'success': False,
            'error': 'Assessment is finalized. Answers can no longer be modified.',
            'finalized': True,
            'redirect_url': reverse('test_results', args=[attempt.attempt_id]),
        }, status=400)

    # Server-side timer expiry check
    if attempt.is_expired:
        evaluate_attempt(attempt, submission_reason='timeout')
        return JsonResponse({
            'success': False,
            'error': 'Assessment time limit reached. Test submitted automatically.',
            'expired': True,
            'redirect_url': reverse('test_results', args=[attempt.attempt_id]),
        }, status=400)

    # Parse input from JSON or standard POST
    payload = {}
    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)
    else:
        payload = request.POST

    question_order_raw = payload.get('question_order')
    question_id_raw = payload.get('question_id')
    selected_option_raw = payload.get('selected_option')

    # Locate the AttemptQuestion record
    aq = None
    if question_order_raw is not None and str(question_order_raw).strip() != '':
        try:
            q_order = int(question_order_raw)
            aq = attempt.attempt_questions.filter(question_order=q_order).first()
        except ValueError:
            pass

    if aq is None and question_id_raw:
        aq = attempt.attempt_questions.filter(question__question_id=question_id_raw).first()

    if aq is None:
        return JsonResponse({
            'success': False,
            'error': 'Question does not belong to this attempt.'
        }, status=400)

    # Validate selected option (can be 1, 2, 3, 4, or None to clear)
    selected_option = None
    if selected_option_raw is not None and str(selected_option_raw).strip() != '':
        try:
            selected_option = int(selected_option_raw)
            if selected_option not in [1, 2, 3, 4]:
                return JsonResponse({
                    'success': False,
                    'error': 'Selected option must be 1, 2, 3, or 4.'
                }, status=400)
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid option format.'
            }, status=400)

    # Persist answer
    aq.selected_option = selected_option
    aq.answered_at = timezone.now() if selected_option is not None else None
    aq.save(update_fields=['selected_option', 'answered_at'])

    # Get updated progress stats
    answered_count = attempt.attempt_questions.filter(selected_option__isnull=False).count()
    unanswered_count = attempt.total_questions - answered_count

    return JsonResponse({
        'success': True,
        'question_order': aq.question_order,
        'selected_option': aq.selected_option,
        'answered_count': answered_count,
        'unanswered_count': unanswered_count,
        'remaining_seconds': attempt.remaining_seconds,
    })


@candidate_required
@require_http_methods(["POST"])
def test_submit(request, attempt_id):
    """
    Manual submission endpoint. Idempotent.
    Evaluates score on the server and redirects to the results scorecard.
    """
    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__candidate', 'registration__test'),
        attempt_id=attempt_id
    )

    if attempt.registration.candidate_id != request.candidate_user.candidate_id:
        return HttpResponseForbidden("You are not authorized to submit this attempt.")

    # If already finalized, directly redirect
    if attempt.status in ['completed', 'expired']:
        return redirect('test_results', attempt_id=attempt.attempt_id)

    # Determine submission reason based on server clock
    if attempt.is_expired:
        reason = 'timeout'
        messages.warning(request, "Assessment time expired. Attempt finalized.")
    else:
        reason = 'manual'
        messages.success(request, "Assessment submitted successfully.")

    evaluate_attempt(attempt, submission_reason=reason)
    return redirect('test_results', attempt_id=attempt.attempt_id)


def test_results(request, attempt_id):
    """
    Results scorecard page.
    Accessible only to the candidate who took the test or an authenticated administrator.
    Does NOT reveal correct answer keys to the candidate.
    """
    admin_id = request.session.get('admin_id')
    candidate_id = request.session.get('candidate_id')

    if not admin_id and not candidate_id:
        return redirect('candidate_login')

    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__test', 'registration__candidate'),
        attempt_id=attempt_id
    )

    # Candidate object-level authorization check
    is_admin = False
    if admin_id:
        try:
            request.admin_user = Admin.objects.get(admin_id=admin_id)
            is_admin = True
        except Admin.DoesNotExist:
            pass

    if not is_admin:
        if str(attempt.registration.candidate_id) != str(candidate_id):
            return HttpResponseForbidden("You are not authorized to view these results.")

    # If still in progress, check if expired
    if attempt.status == 'in_progress':
        if attempt.is_expired:
            evaluate_attempt(attempt, submission_reason='timeout')
        elif not is_admin:
            # Candidate cannot view results while attempt is actively in progress
            return redirect('test_take', attempt_id=attempt.attempt_id)

    topic_performance = get_topic_performance(attempt)

    # Format time taken
    seconds = attempt.time_taken_seconds or 0
    mins = seconds // 60
    secs = seconds % 60
    time_taken_formatted = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    context = {
        'attempt': attempt,
        'test': attempt.registration.test,
        'candidate': attempt.registration.candidate,
        'topic_performance': topic_performance,
        'time_taken_formatted': time_taken_formatted,
        'is_admin_view': is_admin,
    }
    return render(request, 'candidate_portal/results.html', context)


def attempt_scorecard_pdf(request, attempt_id):
    """
    Download official examinee scorecard as PDF.
    Restricted to:
      1) The authenticated candidate who owns the attempt.
      2) An authenticated administrator.
    """
    admin_id = request.session.get('admin_id')
    candidate_id = request.session.get('candidate_id')

    if not admin_id and not candidate_id:
        return redirect('candidate_login')

    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__test', 'registration__candidate'),
        attempt_id=attempt_id
    )

    is_admin = False
    if admin_id:
        try:
            request.admin_user = Admin.objects.get(admin_id=admin_id)
            is_admin = True
        except Admin.DoesNotExist:
            pass

    if not is_admin:
        if str(attempt.registration.candidate_id) != str(candidate_id):
            return HttpResponseForbidden("You are not authorized to download this scorecard.")

    # If still in progress, check if expired
    if attempt.status == 'in_progress':
        if attempt.is_expired:
            evaluate_attempt(attempt, submission_reason='timeout')
        else:
            messages.warning(request, "Assessment must be finalized before downloading official scorecard.")
            return redirect('test_take', attempt_id=attempt.attempt_id)

    from analytics.pdf_export import generate_candidate_scorecard_pdf
    pdf_bytes = generate_candidate_scorecard_pdf(attempt)

    import re
    safe_cand = re.sub(r'[^a-zA-Z0-9_-]', '_', attempt.registration.candidate.name)[:20]
    safe_test = re.sub(r'[^a-zA-Z0-9_-]', '_', attempt.registration.test.test_name)[:20]
    filename = f"HireScan_Scorecard_{safe_cand}_{safe_test}.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

