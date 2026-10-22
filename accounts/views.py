"""
Views for authentication: admin login, candidate OTP login, logout, and homepage.
"""
import secrets
import json
import math
import logging
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.cache import cache
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import timedelta

from accounts.models import Admin, Candidate, OTPVerification, ActivityLog

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Safely resolve client IP address handling proxies and direct connections."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


# ──────────────────────────── Public Homepage ────────────────────────────

def homepage(request):
    """Public landing page at /."""
    return render(request, 'public/homepage.html')


# ──────────────────────────── Admin Login ────────────────────────────

@require_http_methods(["GET", "POST"])
def admin_login(request):
    """Admin login with email + password and safe redirect protection."""
    next_url = request.POST.get('next') or request.GET.get('next', '')

    if request.session.get('admin_id'):
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('admin_dashboard')

    errors = {}

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        # Validation
        if not email:
            errors['email'] = 'Email is required.'
        if not password:
            errors['password'] = 'Password is required.'

        if not errors:
            try:
                admin = Admin.objects.get(email=email)
                if admin.check_password(password):
                    # Successful login
                    request.session.flush()
                    request.session['admin_id'] = str(admin.admin_id)
                    request.session['user_role'] = 'admin'
                    request.session['user_name'] = admin.name
                    request.session['user_email'] = admin.email

                    ActivityLog.objects.create(
                        admin=admin,
                        activity_type='admin_login',
                        activity_details=f'Admin {admin.name} logged in successfully.'
                    )
                    # Validate and execute safe redirect
                    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                        return redirect(next_url)
                    return redirect('admin_dashboard')
                else:
                    errors['general'] = 'Invalid email or password.'
            except Admin.DoesNotExist:
                # Generic error to prevent email enumeration
                errors['general'] = 'Invalid email or password.'

        # Log failed attempt
        ActivityLog.objects.create(
            activity_type='admin_login_failed',
            activity_details=f'Failed login attempt for email: {email}'
        )

    return render(request, 'accounts/admin_login.html', {'errors': errors, 'next': next_url})


# ──────────────────────────── Candidate Login ────────────────────────────

@require_http_methods(["GET", "POST"])
def candidate_login(request):
    """Candidate login page — email entry and OTP verification."""
    if request.session.get('candidate_id'):
        return redirect('candidate_dashboard')
    return render(request, 'accounts/candidate_login.html')


@require_http_methods(["POST"])
def candidate_send_otp(request):
    """Send OTP to candidate's registered email with rate-limiting protection."""
    client_ip = get_client_ip(request)
    rate_limit = getattr(settings, 'OTP_IP_RATE_LIMIT_PER_MINUTE', 5)
    enforce_rate_limit = not getattr(settings, 'IS_TESTING', False) or getattr(settings, 'ENFORCE_OTP_RATE_LIMIT_IN_TESTS', False)

    if enforce_rate_limit:
        cache_key = f"otp_rate_limit_{client_ip}"
        request_count = cache.get(cache_key, 0)
        if request_count >= rate_limit:
            logger.warning("OTP send rate limit exceeded for client IP: %s", client_ip)
            return JsonResponse({
                'success': False,
                'error': 'Too many verification code requests. Please wait a minute before requesting another code.'
            }, status=429)
        cache.set(cache_key, request_count + 1, timeout=60)

    email = request.POST.get('email', '').strip().lower()

    if not email:
        return JsonResponse({'success': False, 'error': 'Email is required.'})

    # Check if candidate exists (generic response to prevent enumeration)
    try:
        candidate = Candidate.objects.get(email=email)
    except Candidate.DoesNotExist:
        # Return same success message to prevent email enumeration
        return JsonResponse({
            'success': True,
            'message': 'If an account exists with this email, an OTP has been sent.'
        })

    # Check resend cooldown on any recently generated OTP for this candidate
    recent_otp = OTPVerification.objects.filter(
        candidate=candidate,
        created_at__gte=timezone.now() - timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    ).order_by('-created_at').first()

    if recent_otp:
        remaining = settings.OTP_RESEND_COOLDOWN_SECONDS - (
            timezone.now() - recent_otp.created_at
        ).total_seconds()
        wait_seconds = max(1, int(math.ceil(remaining)))
        return JsonResponse({
            'success': False,
            'error': f'Please wait {wait_seconds} seconds before requesting a new OTP.'
        })

    # Invalidate previous unused OTPs
    OTPVerification.objects.filter(
        candidate=candidate, is_used=False
    ).update(is_used=True)

    # Generate new OTP
    otp_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])

    # Create OTP record with hashed OTP
    otp_record = OTPVerification(
        candidate=candidate,
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
    )
    otp_record.set_otp(otp_code)
    otp_record.save()

    # Send OTP via email
    try:
        now_local = timezone.localtime(timezone.now())
        expires_local = timezone.localtime(otp_record.expires_at)
        expires_time_str = expires_local.strftime('%I:%M %p')
        local_time_str = now_local.strftime('%I:%M:%S %p')

        email_context = {
            'candidate_name': candidate.name,
            'otp_code': otp_code,
            'expiry_minutes': settings.OTP_EXPIRY_MINUTES,
            'expires_time': expires_time_str,
            'generated_time': local_time_str,
        }
        html_message = render_to_string('emails/otp_email.html', email_context)
        plain_text_message = (
            f"Hello {candidate.name},\n\n"
            f"Your one-time login code is: {otp_code}\n\n"
            f"Generated at: {local_time_str} (expires in {settings.OTP_EXPIRY_MINUTES} minutes, at {expires_time_str}).\n\n"
            f"SECURITY ALERT: Do not share this code with anyone. HireScan staff will never ask for your verification code.\n\n"
            f"Note: If you requested multiple codes, only this latest code is valid.\n\n"
            f"If you did not request this code, please ignore this email.\n\n"
            f"— HireScan Test Management Tool\n"
            f"Secure Session Authentication • Role-Based Access Control"
        )

        send_mail(
            subject='HireScan — Your Login OTP',
            message=plain_text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidate.email],
            fail_silently=False,
            html_message=html_message,
        )
    except Exception as exc:
        logger.error("Failed to deliver OTP email to candidate %s: %s", candidate.email, exc)
        # Invalidate/delete the undelivered OTP so it cannot be used or cause cooldown lockouts
        otp_record.delete()
        ActivityLog.objects.create(
            candidate=candidate,
            activity_type='otp_delivery_failed',
            activity_details=f'Failed to deliver OTP email to {candidate.email}'
        )
        return JsonResponse({
            'success': False,
            'error': 'Unable to deliver verification code at this time. Please check your email configuration or try again shortly.'
        })

    # Store candidate email in session for OTP verification step
    request.session['otp_email'] = email
    request.session['otp_id'] = str(otp_record.otp_id)

    ActivityLog.objects.create(
        candidate=candidate,
        activity_type='otp_sent',
        activity_details=f'OTP sent to {candidate.email}'
    )

    return JsonResponse({
        'success': True,
        'message': 'If an account exists with this email, an OTP has been sent.'
    })


@require_http_methods(["POST"])
def candidate_verify_otp(request):
    """Verify the OTP entered by the candidate."""
    email = request.session.get('otp_email', '')
    otp_code = request.POST.get('otp', '').strip()

    if not email or not otp_code:
        return JsonResponse({'success': False, 'error': 'Invalid request.'})

    try:
        candidate = Candidate.objects.get(email=email)
    except Candidate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Invalid verification attempt.'})

    # Get the latest unused OTP for this candidate
    otp_record = OTPVerification.objects.filter(
        candidate=candidate,
        is_used=False,
    ).order_by('-created_at').first()

    if not otp_record:
        # Check if the code matches a recently superseded OTP to give helpful feedback
        superseded_records = OTPVerification.objects.filter(
            candidate=candidate,
            is_used=True,
            created_at__gte=timezone.now() - timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        ).order_by('-created_at')
        for superseded in superseded_records:
            if superseded.check_otp(otp_code):
                return JsonResponse({
                    'success': False,
                    'error': 'This code has expired or was replaced by a newer OTP request. Please enter the latest code sent to your email.'
                })
        return JsonResponse({'success': False, 'error': 'No active OTP found. Please request a new one.'})

    # Check if expired
    if otp_record.is_expired:
        otp_record.is_used = True
        otp_record.save()
        return JsonResponse({'success': False, 'error': 'OTP has expired. Please request a new one.'})

    # Check attempt limit
    if otp_record.attempts >= settings.OTP_MAX_ATTEMPTS:
        otp_record.is_used = True
        otp_record.save()
        return JsonResponse({
            'success': False,
            'error': 'Too many invalid attempts. Please request a new OTP.'
        })

    # Verify OTP
    if otp_record.check_otp(otp_code):
        otp_record.is_used = True
        otp_record.save()

        # Create candidate session
        request.session.flush()
        request.session['candidate_id'] = str(candidate.candidate_id)
        request.session['user_role'] = 'candidate'
        request.session['user_name'] = candidate.name
        request.session['user_email'] = candidate.email

        ActivityLog.objects.create(
            candidate=candidate,
            activity_type='candidate_login',
            activity_details=f'Candidate {candidate.name} logged in successfully.'
        )

        return JsonResponse({'success': True, 'redirect': '/test/dashboard/'})
    else:
        # Increment attempt counter
        otp_record.attempts += 1
        otp_record.save()

        # Check if code matched an older superseded code
        superseded_records = OTPVerification.objects.filter(
            candidate=candidate,
            is_used=True,
            created_at__gte=timezone.now() - timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        ).exclude(otp_id=otp_record.otp_id)
        for superseded in superseded_records:
            if superseded.check_otp(otp_code):
                return JsonResponse({
                    'success': False,
                    'error': 'This code was replaced by a newer OTP request. Please check your inbox for the most recent code.'
                })

        remaining = settings.OTP_MAX_ATTEMPTS - otp_record.attempts
        error_msg = 'Invalid OTP.'
        if remaining > 0:
            error_msg += f' {remaining} attempt(s) remaining.'
        else:
            error_msg = 'Too many invalid attempts. Please request a new OTP.'
            otp_record.is_used = True
            otp_record.save()

        ActivityLog.objects.create(
            candidate=candidate,
            activity_type='otp_verification_failed',
            activity_details=f'Invalid OTP attempt for {candidate.email}'
        )

        return JsonResponse({'success': False, 'error': error_msg})


# ──────────────────────────── Logout ────────────────────────────

def admin_logout(request):
    """Log out the administrator and clear session."""
    admin_id = request.session.get('admin_id')
    if admin_id:
        try:
            admin = Admin.objects.get(admin_id=admin_id)
            ActivityLog.objects.create(
                admin=admin,
                activity_type='admin_logout',
                activity_details=f'Admin {admin.name} logged out.'
            )
        except Admin.DoesNotExist:
            pass
    request.session.flush()
    return redirect('homepage')


def candidate_logout(request):
    """Log out the candidate and clear session."""
    candidate_id = request.session.get('candidate_id')
    if candidate_id:
        try:
            candidate = Candidate.objects.get(candidate_id=candidate_id)
            ActivityLog.objects.create(
                candidate=candidate,
                activity_type='candidate_logout',
                activity_details=f'Candidate {candidate.name} logged out.'
            )
        except Candidate.DoesNotExist:
            pass
    request.session.flush()
    return redirect('homepage')
