"""Test attempt views."""
from django.shortcuts import render
from accounts.decorators import candidate_required
from assessments.models import TestRegistration


@candidate_required
def candidate_dashboard(request):
    """Candidate dashboard — shows assigned tests and their status."""
    candidate = request.candidate_user

    # Get all registrations with related test and attempt data
    registrations = TestRegistration.objects.filter(
        candidate=candidate
    ).select_related('test').prefetch_related('attempt')

    tests = []
    for reg in registrations:
        attempt = getattr(reg, 'attempt', None)
        try:
            attempt = reg.attempt
        except TestRegistration.attempt.RelatedObjectDoesNotExist:
            attempt = None

        tests.append({
            'registration': reg,
            'test': reg.test,
            'attempt': attempt,
            'can_start': reg.test.is_active and attempt is None,
        })

    context = {
        'candidate': candidate,
        'tests': tests,
    }
    return render(request, 'candidate_portal/dashboard.html', context)
