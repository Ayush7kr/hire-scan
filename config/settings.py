"""
Django settings for HireScan project.
Production-hardened configuration supporting both PostgreSQL and SQLite.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if present
load_dotenv(BASE_DIR / '.env')

# ─────────────────────────────────────────────────────────────────────────────
# 1. Core Security & Environment Detection
# ─────────────────────────────────────────────────────────────────────────────
DEV_DEFAULT_SECRET_KEY = 'django-insecure-dev-key-change-in-production-!@#$%^&*()'
SECRET_KEY = os.getenv('SECRET_KEY', DEV_DEFAULT_SECRET_KEY)

# DEBUG evaluation: defaults to True only if explicitly not 'False'/'0'/'no'
DEBUG = os.getenv('DEBUG', 'True').strip().lower() in ('true', '1', 'yes')

# Check if we are running in a test execution context
IS_TESTING = 'test' in sys.argv or 'testserver' in os.getenv('ALLOWED_HOSTS', '')

# Fail safely if in production with insecure or missing SECRET_KEY
if not DEBUG and not IS_TESTING:
    if not SECRET_KEY or SECRET_KEY == DEV_DEFAULT_SECRET_KEY or SECRET_KEY.startswith('django-insecure-'):
        raise ImproperlyConfigured(
            "CRITICAL SECURITY ERROR: SECRET_KEY must be set to a secure, unique string "
            "in production environments when DEBUG=False. Never use default or insecure keys."
        )

# Host validation
raw_allowed_hosts = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')
ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(',') if h.strip()]

# Trusted origins for CSRF protection
raw_csrf_trusted = os.getenv('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in raw_csrf_trusted.split(',') if o.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# 2. Installed Applications
# ─────────────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # HireScan core apps
    'accounts',
    'candidates',
    'assessments',
    'attempts',
    'analytics',
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. Middleware Pipeline
# ─────────────────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves static files directly in production with compression & caching
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# ─────────────────────────────────────────────────────────────────────────────
# 4. Templates
# ─────────────────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ─────────────────────────────────────────────────────────────────────────────
# 5. Database Selection (PostgreSQL or SQLite)
# ─────────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv('DATABASE_URL')
DB_ENGINE = os.getenv('DB_ENGINE', '').strip().lower()

if DATABASE_URL:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.getenv('DB_CONN_MAX_AGE', 600)),
            conn_health_checks=True,
        )
    }
elif DB_ENGINE in ('postgresql', 'postgres', 'django.db.backends.postgresql'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'hirescan_db'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', 600)),
            'OPTIONS': {
                'connect_timeout': int(os.getenv('DB_CONNECT_TIMEOUT', 10)),
            },
        }
    }
else:
    # Default to SQLite for easy local development and test suite execution
    sqlite_filename = os.getenv('SQLITE_DB_NAME', 'db.sqlite3')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / sqlite_filename,
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# 6. Password Hashers
# ─────────────────────────────────────────────────────────────────────────────
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# ─────────────────────────────────────────────────────────────────────────────
# 7. Internationalization & Timezone
# ─────────────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# ─────────────────────────────────────────────────────────────────────────────
# 8. Static & Media Files (WhiteNoise Production Ready)
# ─────────────────────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
if DEBUG or IS_TESTING:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
else:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
WHITENOISE_MANIFEST_STRICT = False

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─────────────────────────────────────────────────────────────────────────────
# 9. Session Security
# ─────────────────────────────────────────────────────────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', 86400))  # 24 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_SAVE_EVERY_REQUEST = True

# ─────────────────────────────────────────────────────────────────────────────
# 10. Production Security Hardening & Reverse Proxy Headers
# ─────────────────────────────────────────────────────────────────────────────
# Basic protections active across all environments
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'

# SSL & Secure Cookies
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1')
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False' if DEBUG else 'True').lower() in ('true', '1')
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'False' if DEBUG else 'True').lower() in ('true', '1')

# Reverse proxy protocol headers (trusted proxy terminates SSL)
if os.getenv('SECURE_PROXY_SSL_HEADER', 'False').lower() in ('true', '1'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_PROXY_SSL_HEADER = None

USE_X_FORWARDED_HOST = os.getenv('USE_X_FORWARDED_HOST', 'False').lower() in ('true', '1')
USE_X_FORWARDED_PORT = os.getenv('USE_X_FORWARDED_PORT', 'False').lower() in ('true', '1')

# HTTP Strict Transport Security (HSTS)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', 0 if DEBUG else 31536000))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False' if DEBUG else 'True').lower() in ('true', '1')
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'False' if DEBUG else 'True').lower() in ('true', '1')

# ─────────────────────────────────────────────────────────────────────────────
# 11. Email & Candidate Authentication Settings
# ─────────────────────────────────────────────────────────────────────────────
env_email_backend = os.getenv('EMAIL_BACKEND', '').strip()
if env_email_backend:
    EMAIL_BACKEND = env_email_backend
elif DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '').strip()
if 'smtp.gmail.com' in EMAIL_HOST:
    EMAIL_HOST_PASSWORD = EMAIL_HOST_PASSWORD.replace(' ', '')
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', 10))

# Align default sender with authenticated SMTP user if provided
if EMAIL_HOST_USER:
    default_from_addr = f'HireScan <{EMAIL_HOST_USER}>'
else:
    default_from_addr = 'HireScan <noreply@hirescan.local>'

DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', default_from_addr)

# OTP Authentication Settings
OTP_EXPIRY_MINUTES = int(os.getenv('OTP_EXPIRY_MINUTES', 5))
OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', 3))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('OTP_RESEND_COOLDOWN_SECONDS', 60))

# ─────────────────────────────────────────────────────────────────────────────
# 12. Structured Application Logging
# ─────────────────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] [{levelname}] [{name}]: {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{levelname}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'candidates': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'assessments': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'attempts': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'analytics': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LOGIN_URL = '/accounts/login/'
