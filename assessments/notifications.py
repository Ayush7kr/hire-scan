"""
Assessment Email Notification and Reminder Services for HireScan.

Handles branded HTML/plain-text email dispatch for:
1. Candidate registration confirmations.
2. Assessment availability updates.
3. Upcoming examination and deadline reminders.
4. Schedule modifications and cancellation notices.

Enforces anti-duplicate safeguards via NotificationLog, safely isolates SMTP errors,
and audits dispatch operations without leaking sensitive credentials.
"""
import logging
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from accounts.models import ActivityLog
from assessments.models import NotificationLog

logger = logging.getLogger(__name__)


def _format_datetime(dt):
    """Format a datetime into a readable local string."""
    if not dt:
        return ""
    try:
        local_dt = timezone.localtime(dt)
        return local_dt.strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        return str(dt)


def send_registration_notification(candidate, test, request=None):
    """
    Send an assessment registration confirmation email to an active candidate.
    Guards against duplicate notifications.
    """
    if not candidate or not candidate.is_active or not test:
        return False, "Candidate or test is invalid or inactive."

    # Anti-duplicate check
    already_sent = NotificationLog.objects.filter(
        candidate=candidate,
        test=test,
        notification_type='registered',
        status='sent'
    ).exists()
    if already_sent:
        return True, "Notification already delivered previously."

    subject = f"HireScan — You have been registered for '{test.test_name}'"
    start_str = _format_datetime(test.start_time)
    end_str = _format_datetime(test.end_time)

    context = {
        'candidate_name': candidate.name,
        'notification_title': 'Assessment Registration Confirmation',
        'lead_message': (
            f"You have been successfully registered for the technical assessment '{test.test_name}'. "
            f"Please review the assessment details and instructions below."
        ),
        'test_name': test.test_name,
        'description': test.description,
        'duration_minutes': test.duration_minutes,
        'total_questions': test.total_questions,
        'passing_marks': test.passing_marks,
        'status_display': test.status_display,
        'start_time_str': start_str,
        'end_time_str': end_str,
        'notice_title': 'Important Examination Information',
        'notice_text': (
            f"This is a timed examination lasting {test.duration_minutes} minutes. "
            "Once started, the countdown timer cannot be paused. Ensure you have a stable "
            "internet connection before launching."
        ),
        'notice_type': 'info',
        'cta_text': 'Go to Candidate Portal',
        'cta_url': 'http://127.0.0.1:8000/candidate/login/' if not request else request.build_absolute_uri('/candidate/login/'),
    }

    plain_text = (
        f"Hello {candidate.name},\n\n"
        f"You have been registered for the assessment: {test.test_name}\n\n"
        f"Details:\n"
        f"- Duration: {test.duration_minutes} minutes\n"
        f"- Total Questions: {test.total_questions} questions (MCQ)\n"
        f"- Passing Marks: {test.passing_marks} / {test.total_questions}\n"
    )
    if start_str:
        plain_text += f"- Window Opens: {start_str}\n"
    if end_str:
        plain_text += f"- Window Closes: {end_str}\n"
    plain_text += f"- Current Status: {test.status_display}\n\n"
    plain_text += (
        "To take this assessment, sign in to the HireScan Candidate Portal using your "
        "registered email address and a passwordless one-time verification code (OTP).\n\n"
        "— HireScan Test Management Tool\n"
        "Secure Session Authentication • Role-Based Access Control"
    )

    try:
        html_message = render_to_string('emails/assessment_notification.html', context)
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidate.email],
            fail_silently=False,
            html_message=html_message,
        )
        NotificationLog.objects.create(
            candidate=candidate,
            test=test,
            notification_type='registered',
            recipient_email=candidate.email,
            subject=subject,
            status='sent'
        )
        return True, "Notification sent successfully."
    except Exception as exc:
        logger.error("Failed to deliver registration email to %s: %s", candidate.email, exc)
        NotificationLog.objects.create(
            candidate=candidate,
            test=test,
            notification_type='registered',
            recipient_email=candidate.email,
            subject=subject,
            status='failed',
            error_message=str(exc)
        )
        return False, str(exc)


def send_assessment_available_notifications(test, request=None):
    """
    Notify registered candidates when an assessment is published/activated.
    """
    if not test or not test.is_active or test.is_cancelled:
        return 0, 0

    registrations = test.registrations.filter(
        status='registered',
        candidate__is_active=True
    ).select_related('candidate')

    sent_count = 0
    fail_count = 0

    start_str = _format_datetime(test.start_time)
    end_str = _format_datetime(test.end_time)
    subject = f"HireScan — Assessment '{test.test_name}' is now Open"

    for reg in registrations:
        candidate = reg.candidate
        # Check duplicate
        if NotificationLog.objects.filter(
            candidate=candidate, test=test, notification_type='available', status='sent'
        ).exists():
            continue

        context = {
            'candidate_name': candidate.name,
            'notification_title': 'Assessment Now Available',
            'lead_message': f"The examination '{test.test_name}' has been activated and is now ready for attempts.",
            'test_name': test.test_name,
            'description': test.description,
            'duration_minutes': test.duration_minutes,
            'total_questions': test.total_questions,
            'passing_marks': test.passing_marks,
            'status_display': test.status_display,
            'start_time_str': start_str,
            'end_time_str': end_str,
            'notice_title': 'Ready to Begin',
            'notice_text': "You can now log in to the Candidate Portal and begin your assessment.",
            'notice_type': 'info',
            'cta_text': 'Launch Assessment',
            'cta_url': 'http://127.0.0.1:8000/candidate/login/' if not request else request.build_absolute_uri('/candidate/login/'),
        }

        plain_text = (
            f"Hello {candidate.name},\n\n"
            f"The assessment '{test.test_name}' is now open for attempts.\n\n"
            f"Duration: {test.duration_minutes} minutes | Questions: {test.total_questions}\n"
            f"Log in to the Candidate Portal to begin.\n\n"
            "— HireScan Test Management Tool"
        )

        try:
            html_message = render_to_string('emails/assessment_notification.html', context)
            send_mail(
                subject=subject,
                message=plain_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[candidate.email],
                fail_silently=False,
                html_message=html_message,
            )
            NotificationLog.objects.create(
                candidate=candidate,
                test=test,
                notification_type='available',
                recipient_email=candidate.email,
                subject=subject,
                status='sent'
            )
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to deliver available notification to %s: %s", candidate.email, exc)
            NotificationLog.objects.create(
                candidate=candidate,
                test=test,
                notification_type='available',
                recipient_email=candidate.email,
                subject=subject,
                status='failed',
                error_message=str(exc)
            )
            fail_count += 1

    return sent_count, fail_count


def send_assessment_reminder_notification(candidate, test, reminder_type='upcoming', request=None):
    """
    Send an upcoming examination or approaching deadline reminder.
    """
    if not candidate or not candidate.is_active or not test or test.is_cancelled:
        return False, "Candidate or test not eligible for reminder."

    # Avoid duplicate reminders for same type
    already_sent = NotificationLog.objects.filter(
        candidate=candidate,
        test=test,
        notification_type='reminder',
        status='sent'
    ).exists()
    if already_sent:
        return True, "Reminder already dispatched."

    subject = f"HireScan Reminder — '{test.test_name}' Assessment Window"
    start_str = _format_datetime(test.start_time)
    end_str = _format_datetime(test.end_time)

    context = {
        'candidate_name': candidate.name,
        'notification_title': 'Upcoming Assessment Reminder',
        'lead_message': (
            f"This is a friendly reminder regarding your registered assessment '{test.test_name}'. "
            f"Please check your schedule window to ensure you complete your assessment on time."
        ),
        'test_name': test.test_name,
        'description': test.description,
        'duration_minutes': test.duration_minutes,
        'total_questions': test.total_questions,
        'passing_marks': test.passing_marks,
        'status_display': test.status_display,
        'start_time_str': start_str,
        'end_time_str': end_str,
        'notice_title': 'Important Schedule Reminder',
        'notice_text': "Assessments must be submitted before the closing window. Unsubmitted attempts will automatically expire.",
        'notice_type': 'warning',
        'cta_text': 'Go to Candidate Portal',
        'cta_url': 'http://127.0.0.1:8000/candidate/login/' if not request else request.build_absolute_uri('/candidate/login/'),
    }

    plain_text = (
        f"Hello {candidate.name},\n\n"
        f"Reminder: You are registered for the assessment '{test.test_name}'.\n"
        f"Duration: {test.duration_minutes} minutes | Questions: {test.total_questions}\n"
    )
    if start_str:
        plain_text += f"Window Opens: {start_str}\n"
    if end_str:
        plain_text += f"Window Closes: {end_str}\n"
    plain_text += "\n— HireScan Test Management Tool"

    try:
        html_message = render_to_string('emails/assessment_notification.html', context)
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidate.email],
            fail_silently=False,
            html_message=html_message,
        )
        NotificationLog.objects.create(
            candidate=candidate,
            test=test,
            notification_type='reminder',
            recipient_email=candidate.email,
            subject=subject,
            status='sent'
        )
        return True, "Reminder sent successfully."
    except Exception as exc:
        logger.error("Failed to deliver reminder email to %s: %s", candidate.email, exc)
        NotificationLog.objects.create(
            candidate=candidate,
            test=test,
            notification_type='reminder',
            recipient_email=candidate.email,
            subject=subject,
            status='failed',
            error_message=str(exc)
        )
        return False, str(exc)


def send_assessment_cancelled_notifications(test, request=None):
    """
    Notify registered candidates when an assessment is cancelled by an administrator.
    """
    if not test or not test.is_cancelled:
        return 0, 0

    registrations = test.registrations.filter(
        status='registered',
        candidate__is_active=True
    ).select_related('candidate')

    sent_count = 0
    fail_count = 0
    subject = f"HireScan Notice — Assessment '{test.test_name}' has been Cancelled"

    for reg in registrations:
        candidate = reg.candidate
        if NotificationLog.objects.filter(
            candidate=candidate, test=test, notification_type='cancelled', status='sent'
        ).exists():
            continue

        context = {
            'candidate_name': candidate.name,
            'notification_title': 'Assessment Cancelled Notice',
            'lead_message': f"Please note that the examination '{test.test_name}' has been cancelled by the test administrator.",
            'test_name': test.test_name,
            'description': test.description,
            'duration_minutes': test.duration_minutes,
            'total_questions': test.total_questions,
            'passing_marks': test.passing_marks,
            'status_display': 'Cancelled',
            'start_time_str': '',
            'end_time_str': '',
            'notice_title': 'Cancellation Advisory',
            'notice_text': "This test is no longer open for candidate attempts. Contact your test administrator if you have questions.",
            'notice_type': 'danger',
            'cta_text': '',
            'cta_url': '',
        }

        plain_text = (
            f"Hello {candidate.name},\n\n"
            f"Notice: The assessment '{test.test_name}' has been cancelled by the test administrator.\n"
            f"Attempts are no longer permitted.\n\n"
            "— HireScan Test Management Tool"
        )

        try:
            html_message = render_to_string('emails/assessment_notification.html', context)
            send_mail(
                subject=subject,
                message=plain_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[candidate.email],
                fail_silently=False,
                html_message=html_message,
            )
            NotificationLog.objects.create(
                candidate=candidate,
                test=test,
                notification_type='cancelled',
                recipient_email=candidate.email,
                subject=subject,
                status='sent'
            )
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to deliver cancellation notice to %s: %s", candidate.email, exc)
            NotificationLog.objects.create(
                candidate=candidate,
                test=test,
                notification_type='cancelled',
                recipient_email=candidate.email,
                subject=subject,
                status='failed',
                error_message=str(exc)
            )
            fail_count += 1

    return sent_count, fail_count
