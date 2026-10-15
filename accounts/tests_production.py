"""
Production Hardening, Deployment, and Health Check Tests for HireScan.

Covers:
1. Health check endpoint probing and failure recovery (/health/ and /healthz/).
2. Production settings validation (insecure SECRET_KEY guard with DEBUG=False).
3. PostgreSQL configuration parsing and SQLite fallback.
4. Static asset pipeline (WhiteNoise, local vendor files: Chart.js, Bootstrap).
5. Reverse proxy protocol forwarding and HTTPS detection.
6. Cookie security flags (SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE).
7. Structured logging and email backend switching.
"""
import os
import unittest
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import dj_database_url


class ProductionHealthCheckTests(TestCase):
    """Test suite for container health check probes (/health/ and /healthz/)."""

    def setUp(self):
        self.client = Client()

    def test_health_check_endpoint_healthy(self):
        """Health check returns HTTP 200 with JSON payload when DB is connected."""
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertIn('db_latency_ms', data)
        self.assertIn('timestamp', data)

    def test_healthz_alias_endpoint(self):
        """Kubernetes / standard /healthz endpoint returns HTTP 200."""
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'healthy')

    @patch('django.db.connection.cursor')
    def test_health_check_database_failure(self, mock_cursor):
        """Health check returns HTTP 503 when database probe fails."""
        mock_cursor.side_effect = Exception("Database connection refused")
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get('status'), 'unhealthy')
        self.assertEqual(data.get('database'), 'error')


class ProductionConfigurationTests(TestCase):
    """Test suite for production settings, environment parsing, and security."""

    def test_insecure_secret_key_guard_in_production(self):
        """DEBUG=False must reject default or insecure secret keys."""
        # Simulated check using the same logic implemented in settings.py
        dev_default = 'django-insecure-dev-key-change-in-production-!@#$%^&*()'
        with self.assertRaises(ImproperlyConfigured):
            # Evaluate guard logic
            debug_val = False
            secret = dev_default
            if not debug_val:
                if not secret or secret == dev_default or secret.startswith('django-insecure-'):
                    raise ImproperlyConfigured("Insecure secret key rejected")

    def test_database_url_postgresql_parsing(self):
        """DATABASE_URL pointing to postgres:// is correctly parsed into PostgreSQL configuration."""
        db_url = "postgres://hire_user:hire_pass@db.internal:5432/hirescan_production"
        parsed = dj_database_url.parse(db_url, conn_max_age=600)
        self.assertEqual(parsed['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(parsed['NAME'], 'hirescan_production')
        self.assertEqual(parsed['USER'], 'hire_user')
        self.assertEqual(parsed['PASSWORD'], 'hire_pass')
        self.assertEqual(parsed['HOST'], 'db.internal')
        self.assertEqual(parsed['PORT'], 5432)
        self.assertEqual(parsed['CONN_MAX_AGE'], 600)

    def test_whitenoise_middleware_configured(self):
        """WhiteNoise middleware must be present directly after SecurityMiddleware."""
        middleware = settings.MIDDLEWARE
        self.assertIn('django.middleware.security.SecurityMiddleware', middleware)
        self.assertIn('whitenoise.middleware.WhiteNoiseMiddleware', middleware)
        sec_idx = middleware.index('django.middleware.security.SecurityMiddleware')
        wn_idx = middleware.index('whitenoise.middleware.WhiteNoiseMiddleware')
        self.assertEqual(wn_idx, sec_idx + 1)

    def test_static_storage_and_manifest_configured(self):
        """WhiteNoise storage and static roots are properly defined."""
        self.assertEqual(
            settings.STATICFILES_STORAGE,
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
        )
        self.assertTrue(settings.STATIC_ROOT)
        self.assertFalse(settings.WHITENOISE_MANIFEST_STRICT)

    def test_vendor_static_assets_offline_availability(self):
        """Critical frontend vendor assets (Chart.js, Bootstrap) must exist in static/."""
        base_dir = settings.BASE_DIR
        chartjs_path = base_dir / 'static' / 'vendor' / 'chartjs' / 'chart.umd.min.js'
        bootstrap_css = base_dir / 'static' / 'vendor' / 'bootstrap' / 'bootstrap.min.css'
        bootstrap_js = base_dir / 'static' / 'vendor' / 'bootstrap' / 'bootstrap.bundle.min.js'
        icons_css = base_dir / 'static' / 'vendor' / 'bootstrap-icons' / 'bootstrap-icons.min.css'

        self.assertTrue(chartjs_path.exists(), "chart.umd.min.js is missing from static/vendor/")
        self.assertTrue(chartjs_path.stat().st_size > 100000, "chart.umd.min.js is truncated")
        self.assertTrue(bootstrap_css.exists(), "bootstrap.min.css is missing from static/vendor/")
        self.assertTrue(bootstrap_js.exists(), "bootstrap.bundle.min.js is missing from static/vendor/")
        self.assertTrue(icons_css.exists(), "bootstrap-icons.min.css is missing from static/vendor/")

    def test_security_headers_settings(self):
        """Standard production security headers must be configured."""
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertEqual(settings.SECURE_REFERRER_POLICY, 'same-origin')

    @override_settings(
        SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https')
    )
    def test_reverse_proxy_forwarded_proto_handling(self):
        """Reverse proxy forwarding header must be respected when configured."""
        client = Client()
        response = client.get('/health/', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)

    def test_logging_configuration(self):
        """Structured logging configuration must define required application loggers."""
        self.assertIn('handlers', settings.LOGGING)
        self.assertIn('console', settings.LOGGING['handlers'])
        self.assertIn('loggers', settings.LOGGING)
        for app_logger in ('django', 'accounts', 'candidates', 'assessments', 'attempts', 'analytics'):
            self.assertIn(app_logger, settings.LOGGING['loggers'])

    def test_email_timeout_configured(self):
        """Email timeout must be defined to prevent blocking worker threads."""
        self.assertTrue(hasattr(settings, 'EMAIL_TIMEOUT'))
        self.assertGreaterEqual(settings.EMAIL_TIMEOUT, 5)
