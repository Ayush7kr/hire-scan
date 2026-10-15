# syntax=docker/dockerfile:1
# ==============================================================================
# HireScan — Production Container Dockerfile
# Python 3.12 LTS on Debian Slim
# ==============================================================================

FROM python:3.12-slim as base

# Set non-interactive debian frontend and python optimizations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PORT=8000

# Install runtime system packages (curl for healthcheck, libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Create a non-privileged dedicated application user and group
RUN groupadd -g 1001 hirescan && \
    useradd -u 1001 -g hirescan -s /bin/sh -m hirescan

# Create static and media directories with proper ownership
RUN mkdir -p /app/staticfiles /app/media && \
    chown -R hirescan:hirescan /app/staticfiles /app/media

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=hirescan:hirescan . /app/

# Ensure startup script is executable
RUN chmod +x /app/entrypoint.sh

# Switch to non-root user
USER hirescan

# Expose internal Gunicorn application port
EXPOSE 8000

# Container health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# Controlled initialization and startup
ENTRYPOINT ["/app/entrypoint.sh"]

# Default execution command: start production Gunicorn server
CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
