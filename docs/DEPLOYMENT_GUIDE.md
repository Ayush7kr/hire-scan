# HireScan — Production Deployment & Operations Guide

This guide provides instructions for deploying **HireScan — Test Management Tool** to staging and production environments using Docker, Docker Compose, PostgreSQL 16, Gunicorn WSGI, and WhiteNoise static asset serving.

---

## Table of Contents
1. [Production Architecture Overview](#1-production-architecture-overview)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Environment Configuration Reference](#3-environment-configuration-reference)
4. [Docker & Docker Compose Deployment](#4-docker--docker-compose-deployment)
5. [Manual / Bare-Metal Production Setup](#5-manual--bare-metal-production-setup)
6. [Database Management & Migration Strategy](#6-database-management--migration-strategy)
7. [Health Checks & Container Monitoring](#7-health-checks--container-monitoring)
8. [Automated CI/CD Pipeline](#8-automated-cicd-pipeline)
9. [Backup & Disaster Recovery](#9-backup--disaster-recovery)
10. [Pre-Flight Production Checklist](#10-pre-flight-production-checklist)

---

## 1. Production Architecture Overview

```mermaid
flowchart TD
    Internet((Internet / HTTPS)) --> ReverseProxy["Reverse Proxy / Ingress<br/>(Nginx / Cloudflare / ALB)"]
    
    subgraph AppHost ["HireScan Application Host"]
        ReverseProxy --> Gunicorn["Gunicorn WSGI Server<br/>(4 Workers, gthread)"]
        Gunicorn --> Django["Django 4.2 Application"]
        Django --> WhiteNoise["WhiteNoise Static Engine<br/>(Compressed, Cached Assets)"]
    end
    
    subgraph DBHost ["Database Host / Managed Cluster"]
        Django --> Postgres[("PostgreSQL 16 Engine<br/>(ACID Transactions, SSL)")]
        Postgres --> DBVolume[("Persistent Storage Volume<br/>/var/lib/postgresql/data")]
    end
```

---

## 2. Prerequisites & System Requirements

- **Operating System:** Linux (Ubuntu 22.04 LTS / Debian 12 recommended) or Windows Server
- **Runtime:** Python 3.12 LTS
- **Database:** PostgreSQL 15+ (PostgreSQL 16 recommended)
- **Containerization (Optional):** Docker 24.0+ and Docker Compose v2+
- **Compute Sizing:**
  - Minimum: 1 vCPU, 2 GB RAM (Up to 200 concurrent candidates)
  - Recommended: 2-4 vCPU, 4-8 GB RAM (Up to 1,500 concurrent candidates)

---

## 3. Environment Configuration Reference

HireScan is configured via environment variables. Copy `.env.example` to `.env` in the deployment root:

```bash
cp .env.example .env
```

### Complete Environment Variable Matrix

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `DJANGO_SECRET_KEY` | **Yes** | — | Cryptographically random string (min 50 chars) used for HMAC signing. |
| `DJANGO_DEBUG` | **Yes** | `False` | Must be `False` in production to prevent information disclosure. |
| `DJANGO_ALLOWED_HOSTS` | **Yes** | `localhost,127.0.0.1` | Comma-delimited list of hostnames/domains permitted to serve requests. |
| `DJANGO_PRODUCTION` | No | `False` | Set to `True` to activate strict HSTS, HTTPS redirects, and secure cookies. |
| `DATABASE_URL` | No | SQLite local | PostgreSQL connection URI: `postgres://user:pass@host:5432/dbname`. |
| `DB_ENGINE` | No | `django.db.backends.sqlite3` | Set to `django.db.backends.postgresql` when configuring discrete DB vars. |
| `DB_NAME` | No | `hirescan` | PostgreSQL database name. |
| `DB_USER` | No | `postgres` | PostgreSQL username. |
| `DB_PASSWORD` | No | — | PostgreSQL password. |
| `DB_HOST` | No | `db` | Database hostname or container service name. |
| `DB_PORT` | No | `5432` | Database port. |
| `EMAIL_BACKEND` | No | `smtp` | Set to `django.core.mail.backends.smtp.EmailBackend` for live OTP emails. |
| `EMAIL_HOST` | No | `smtp.gmail.com` | SMTP relay server hostname. |
| `EMAIL_PORT` | No | `587` | SMTP port (587 for TLS, 465 for SSL). |
| `EMAIL_USE_TLS` | No | `True` | Enforce TLS encryption for outgoing emails. |
| `EMAIL_HOST_USER` | No | — | SMTP authentication username / address. |
| `EMAIL_HOST_PASSWORD` | No | — | SMTP authentication password or App Password. |
| `DEFAULT_FROM_EMAIL` | No | `noreply@hirescan.io` | Outgoing sender address displayed on candidate OTP emails. |

---

## 4. Docker & Docker Compose Deployment

HireScan provides a turnkey, multi-stage `Dockerfile` and `docker-compose.yml` for containerized environments.

### 4.1 Launch with Docker Compose
```bash
# 1. Clone repository
git clone https://github.com/Ayush7kr/hire-scan.git
cd hire-scan

# 2. Configure production secrets
cp .env.example .env
nano .env

# 3. Build containers and start in detached mode
docker compose up -d --build

# 4. Check container health status
docker compose ps
```

### 4.2 Initialize Database & Provision Administrator
```bash
# Run database migrations
docker compose exec web python manage.py migrate --noinput

# Provision initial system administrator
docker compose exec web python manage.py create_admin \
    --email admin@hirescan.io \
    --name "System Administrator" \
    --password "SuperSecretPassword123!"

# Verify deployment health check
curl -I http://localhost:8000/health/
```

---

## 5. Manual / Bare-Metal Production Setup

For deployments directly onto Ubuntu or Debian virtual machines:

```bash
# 1. Install system dependencies
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip postgresql libpq-dev git

# 2. Create dedicated system user
sudo useradd -m -s /bin/bash hirescan
sudo su - hirescan

# 3. Clone and configure virtual environment
git clone https://github.com/Ayush7kr/hire-scan.git app
cd app
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn psycopg2-binary

# 4. Collect static files
python manage.py collectstatic --noinput

# 5. Run migrations
python manage.py migrate --noinput

# 6. Start Gunicorn WSGI Server
gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --threads 2 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
```

---

## 6. Database Management & Migration Strategy

HireScan utilizes Django's migration engine for atomic schema upgrades.

### Safe Migration Workflow
1. **Pre-Migration Backup:** Always take a database snapshot prior to running migrations in production:
   ```bash
   pg_dump -U postgres -d hirescan -F c -b -v -f /backups/hirescan_pre_migrate.dump
   ```
2. **Execute Migrations:**
   ```bash
   python manage.py migrate --noinput
   ```
3. **Verify Integrity:** Run the Django system check to ensure no model conflicts:
   ```bash
   python manage.py check --deploy
   ```

---

## 7. Health Checks & Container Monitoring

HireScan provides built-in HTTP health check endpoints for load balancers and orchestrators:

- **Endpoint:** `GET /health/` or `GET /healthz/`
- **Behavior:**
  - Performs an active database probe (`SELECT 1`).
  - Verifies cache / session accessibility.
  - Returns HTTP 200 with JSON payload:
    ```json
    {
      "status": "healthy",
      "database": "connected",
      "timestamp": "2026-10-20T22:33:52Z"
    }
    ```
  - Returns HTTP 503 if the database or critical subsystems are unreachable.

---

## 8. Automated CI/CD Pipeline

The project includes an enterprise-grade GitHub Actions CI workflow (`.github/workflows/ci.yml`).

### Workflow Steps
1. **Linting & Code Quality:** Enforces PEP 8 style standards with Flake8.
2. **PostgreSQL Service Container:** Boots an ephemeral PostgreSQL 16 instance.
3. **Migration Verification:** Executes `python manage.py migrate` against the clean database.
4. **Automated Test Suite:** Runs all 131 unit, integration, and security tests.
5. **Security & Deployment Audit:** Executes `python manage.py check --deploy`.

---

## 9. Backup & Disaster Recovery

### Automated Backup Script
Create a daily cron job to back up the PostgreSQL database:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/hirescan"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

# Dump PostgreSQL database
pg_dump -h localhost -U postgres -d hirescan -F c -b -v -f "$BACKUP_DIR/hirescan_$TIMESTAMP.dump"

# Retain backups for 30 days
find "$BACKUP_DIR" -type f -name "*.dump" -mtime +30 -delete
```

### Database Restoration
```bash
# Restore from a compressed dump file
pg_restore -h localhost -U postgres -d hirescan --clean --no-owner /var/backups/hirescan/hirescan_latest.dump
```

---

## 10. Pre-Flight Production Checklist

Before admitting candidates to live technical examinations, ensure the following checklist is completed:

- [ ] `DJANGO_DEBUG` is set to `False`.
- [ ] `DJANGO_SECRET_KEY` is set to a unique, secret 64-character token.
- [ ] `DJANGO_ALLOWED_HOSTS` includes only authorized production domain names.
- [ ] `DJANGO_PRODUCTION` is set to `True` (enabling HSTS, secure cookies, and HTTPS redirection).
- [ ] Database credentials point to a resilient PostgreSQL cluster with automated backups.
- [ ] SMTP credentials are verified and delivering candidate OTP emails within 5 seconds.
- [ ] Static files have been compressed and collected via `collectstatic`.
- [ ] System administrator account is provisioned with a secure password.
- [ ] Automated health check at `/health/` returns HTTP 200 OK.
