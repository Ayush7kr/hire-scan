"""
Authorization decorators for role-based access control.
These enforce server-side authentication checks on every protected view.
"""
from functools import wraps
from urllib.parse import quote
from django.shortcuts import redirect
from django.urls import reverse
from django.http import HttpResponseForbidden


def admin_required(view_func):
    """Decorator that ensures only authenticated administrators can access the view."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        admin_id = request.session.get('admin_id')
        if not admin_id:
            path = request.get_full_path()
            if path and path != '/':
                return redirect(f"{reverse('admin_login')}?next={quote(path)}")
            return redirect('admin_login')
        # Verify admin still exists in database
        from accounts.models import Admin
        try:
            admin = Admin.objects.get(admin_id=admin_id)
            request.admin_user = admin
        except Admin.DoesNotExist:
            request.session.flush()
            return redirect('admin_login')
        return view_func(request, *args, **kwargs)
    return wrapper


def candidate_required(view_func):
    """Decorator that ensures only authenticated candidates can access the view."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        candidate_id = request.session.get('candidate_id')
        if not candidate_id:
            return redirect('candidate_login')
        # Verify candidate still exists in database
        from accounts.models import Candidate
        try:
            candidate = Candidate.objects.get(candidate_id=candidate_id)
            request.candidate_user = candidate
        except Candidate.DoesNotExist:
            request.session.flush()
            return redirect('candidate_login')
        return view_func(request, *args, **kwargs)
    return wrapper
