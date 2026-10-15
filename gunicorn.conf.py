"""
Gunicorn configuration file for HireScan production deployment.
"""
import os
import multiprocessing

# Network binding
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# Worker concurrency
# In containerized environments, default to 3 workers or 2 * cores + 1
workers = int(os.getenv("GUNICORN_WORKERS", 3))
threads = int(os.getenv("GUNICORN_THREADS", 2))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")

# Timeout configuration
# Allow up to 90 seconds for large report exports, batch CSV streaming, and PDF rendering
timeout = int(os.getenv("GUNICORN_TIMEOUT", 90))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 30))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

# Process management
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", 50))

# Logging to standard output/error for 12-factor / container log collection
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'

# Server identification
proc_name = "hirescan_gunicorn"
daemon = False
