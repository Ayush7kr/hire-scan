"""
Project-level views for HireScan (e.g. Health Check).
"""
import time
from django.http import JsonResponse
from django.db import connection
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


def health_check(request):
    """
    Production health check endpoint for container orchestrators, load balancers,
    and monitoring agents.
    Verifies that the application process is responsive and that the database is reachable.
    Returns HTTP 200 when healthy, or HTTP 503 when the database is unreachable.
    """
    start_time = time.monotonic()
    db_status = "connected"
    db_latency_ms = None

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_latency_ms = round((time.monotonic() - start_time) * 1000, 2)
    except Exception as exc:
        logger.error("Health check database probe failed: %s", exc)
        return JsonResponse({
            'status': 'unhealthy',
            'database': 'error',
            'error': 'Database probe failed',
            'timestamp': timezone.now().isoformat(),
        }, status=503)

    return JsonResponse({
        'status': 'healthy',
        'database': db_status,
        'db_latency_ms': db_latency_ms,
        'timestamp': timezone.now().isoformat(),
    }, status=200)


def error_400(request, exception=None):
    """Custom 400 Bad Request error view."""
    from django.shortcuts import render
    return render(request, '400.html', status=400)


def error_403(request, exception=None):
    """Custom 403 Forbidden access error view."""
    from django.shortcuts import render
    return render(request, '403.html', status=403)


def error_404(request, exception=None):
    """Custom 404 Not Found error view."""
    from django.shortcuts import render
    return render(request, '404.html', status=404)


def error_500(request):
    """Custom 500 Internal Server Error view."""
    from django.shortcuts import render
    return render(request, '500.html', status=500)
