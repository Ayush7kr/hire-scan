# HireScan — Test Management Tool

HireScan is a secure, maintainable, production-ready web application built to streamline candidate registrations, conduct timed and randomized technical assessments, and evaluate examinee performance with instant server-side scoring and topic analytics.

---

## 1. Technology Stack & Design Architecture

- **Backend:** Python 3.12 & Django 4.2 LTS
- **Frontend:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3, Bootstrap Icons
- **Database:** SQLite (Initial development) with modular transition to PostgreSQL
- **Authentication:**
  - **Administrator:** Django PBKDF2 password hashing with secure HTTP-only session cookies
  - **Candidate:** Passwordless cryptographically secure email OTP verification with attempt limiting and cooldown
- **Architecture Pattern:** Modular Django applications with separation of concerns:
  - `accounts/`: Authentication, sessions, OTP verification, activity auditing, role decorators
  - `candidates/`: Candidate profiles, CSV roster imports, eligibility checks, activation toggling
  - `assessments/`: Tests, question banks (4-option MCQs with topic/difficulty), sufficiency rules, registrations
  - `attempts/`: Test attempts, timer management, autosave responses, server-side scoring
  - `analytics/`: Administrator metrics, pass/fail calculations, reporting

---

## 2. Mandatory Architectural Constraints Observed

1. **No Django Admin:** Custom-built administrator management interface and views.
2. **No Django Forms / ModelForms:** Custom HTML forms with explicit Django validation and CSRF protection.
3. **No Unnecessary Frontend Frameworks:** Native HTML/CSS/JavaScript with Bootstrap 5.
4. **No Public Candidate Sign-Up:** Candidates are imported and registered strictly by administrators.
5. **No Public Admin Registration:** Administrators are provisioned via secure management CLI commands.
6. **No Plaintext Passwords or OTPs:** All passwords and OTPs are hashed using PBKDF2 before storage.
7. **No Answer Leaks:** Correct answer keys are isolated on the server and never exposed to the client prior to finalization.
8. **Enforced Public Homepage:** Public landing page at `/` guides users to appropriate authentication portals.

---

## 3. Database Schema & Entity Relationships

The data layer strictly models the approved ER specifications:

| Entity | Primary Key | Description & Integrity Rules |
| :--- | :--- | :--- |
| `Admin` | `admin_id` (UUID) | System administrator accounts with unique email and hashed password. |
| `Candidate` | `candidate_id` (UUID) | Examinee records created via admin CSV import with unique email and `is_active` flag. |
| `Test` | `test_id` (UUID) | Test configurations with duration, question count, passing threshold, and `is_active` status. |
| `Question` | `question_id` (UUID) | 4-option MCQs belonging to a test bank with topic, difficulty, and suggestions. |
| `TestRegistration` | `registration_id` (UUID) | Links Candidate to Test with `status` ('registered'/'cancelled'). Enforces `UNIQUE(candidate, test)`. |
| `TestAttempt` | `attempt_id` (UUID) | Single attempt per registration via `OneToOneField`. Tracks score and status. |
| `AttemptQuestion` | `aq_id` (UUID) | Assigned question subset per attempt. Enforces `UNIQUE(attempt, question)`. |
| `OTPVerification` | `otp_id` (UUID) | Candidate OTP records with PBKDF2 hash, 5-minute expiry, and max 3 attempts. |
| `ActivityLog` | `activity_id` (UUID) | Audit log for logins, candidate imports, tests, and administrative actions. |

---

## 4. Setup and Installation Instructions

### Prerequisites
- Python 3.10+ (Tested on Python 3.12)
- Git

### 1. Clone & Enter Project Directory
```bash
git clone <repository-url>
cd HireScan
```

### 2. Set Up Virtual Environment (Recommended)
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Key configuration values in `.env`:
- `SECRET_KEY`: Random string for Django cryptographic signing.
- `DEBUG`: Set to `True` for development, `False` for production.
- `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames (e.g., `localhost,127.0.0.1`).
- `EMAIL_BACKEND`: In development (`DEBUG=True`), Django automatically uses the console backend (`django.core.mail.backends.console.EmailBackend`) which prints generated OTPs directly to your terminal.

### 5. Apply Database Migrations
```bash
python manage.py migrate
```

---

## 5. Provisioning an Administrator Account

Administrator accounts cannot be registered publicly. To create an administrator:

```bash
python manage.py create_admin --email admin@hirescan.local --name "HireScan Administrator" --password "YourStrongPassword123!"
```
Or run interactively to prompt for password with confirmation:
```bash
python manage.py create_admin
```

---

## 6. Running the Application Locally

Start the Django development server:
```bash
python manage.py runserver
```

Open your browser and navigate to:
- **Public Homepage:** `http://127.0.0.1:8000/`
- **Administrator Login:** `http://127.0.0.1:8000/admin/login/`
- **Administrator Dashboard:** `http://127.0.0.1:8000/admin/dashboard/`
- **Candidate Roster:** `http://127.0.0.1:8000/admin/candidates/`
- **Candidate CSV Import:** `http://127.0.0.1:8000/admin/candidates/import/`
- **Assessment Tests:** `http://127.0.0.1:8000/admin/tests/`
- **Test Registrations:** `http://127.0.0.1:8000/admin/registrations/`
- **Candidate Login:** `http://127.0.0.1:8000/candidate/login/`
- **Candidate Assessment Portal:** `http://127.0.0.1:8000/test/dashboard/`

---

## 7. CSV Formats Supported

### Candidate Roster CSV Format
Headers:
```csv
email,name,whatsapp_number,college_name_address,qualification,passing_year,other
```
Example:
```csv
john.doe@example.com,John Doe,9876543210,Apex University,B.Tech CS,2025,Software Engineer Applicant
```

### Question Bank CSV Format
Headers:
```csv
question,option1,option2,option3,option4,correct_option,topic,difficulty,suggestions
```
Example:
```csv
What is the output of print(type([])) in Python 3?,<class 'list'>,<class 'tuple'>,<class 'array'>,<class 'dict'>,1,Data Types,easy,Review standard container types.
```
*Note: `correct_option` accepts `1`, `2`, `3`, `4` or `A`, `B`, `C`, `D` (normalized automatically).*

---

## 8. Running the Automated Test Suite

HireScan includes a comprehensive automated test suite covering authentication, route authorization, database constraints, candidate imports, question bank sufficiency, registration rules, assessment engine workflows, server timer enforcement, autosave idempotency, scoring accuracy, and IDOR protection.

Execute the test suite:
```bash
python manage.py test
```

Current test results:
```
Ran 111 tests in 58.915s
OK
```

---

## 9. Development Status & Roadmap

- [x] **Phase 1: Foundation (Completed)**
  - Workspace inspection & approved specification synthesis
  - Django project structure, configuration, and environment handling
  - Full relational schema (Admin, Candidate, Test, Question, Registration, Attempt, AttemptQuestion, OTP, ActivityLog)
  - Public homepage meeting all layout & copy specifications
  - Administrator authentication (email/password with PBKDF2 hashing, session management)
  - Candidate passwordless OTP email authentication (hashed OTP, 5-minute expiry, cooldown)
  - Role-based access control decorators (`@admin_required`, `@candidate_required`)
  - Admin CLI provisioning command (`create_admin`)
  - 20 unit/integration tests passing
- [x] **Phase 2: Administration Module (Completed)**
  - Candidate roster management (list, search, pagination, detail, edit, activate/deactivate)
  - Candidate CSV batch roster imports with field validation, duplicate detection, and downloadable error reports
  - Test management (create, edit, duration/question validation, historical attempt protection)
  - Test activation rules strictly enforced (cannot activate test if bank < total questions)
  - Question bank management (manual add, edit, delete with auto-deactivation safeguard)
  - Question bank CSV import with 4-option validation, normalization (1-4 and A-D), and downloadable error reports
  - Candidate-to-test registration management with `UNIQUE(candidate, test)` duplicate protection
  - Registration cancellation with completed attempt protection
  - Complete integration into the Administrator Dashboard with live metrics
  - 28 new automated tests (48 tests passing in total)
- [x] **Phase 3: Assessment Engine Implementation (Completed)**
  - Candidate dashboard with live assessment status and launch/resume/results routing
  - Pre-assessment instructions briefing with test rules and acknowledgment (`/test/instructions/<registration_id>/`)
  - Transactional attempt creation with atomic locking and single-attempt constraint enforcement (`/test/start/<registration_id>/`)
  - One-time question randomization and stable 1..N order persistence across page reloads
  - Split-pane examination interface with question navigation, countdown timer, and interactive question palette (`/test/take/<attempt_id>/`)
  - Server-authoritative timer deadline validation (`start_time + duration`) on all requests
  - Authenticated background answer autosave endpoint with live status indicators (`/test/autosave/<attempt_id>/`)
  - Idempotent manual and timeout finalization (`/test/submit/<attempt_id>/`)
  - Server-side evaluation service (`attempts/services.py`) computing score, percentage, pass/fail status, and time taken
  - Candidate result scorecard with topic-wise performance breakdown and improvement tips (`/test/results/<attempt_id>/`)
  - Strict answer key isolation (correct options never exposed to candidate in DOM or context)
  - Administrator attempt monitoring and full question audit trail inspection (`/admin/tests/<test_id>/attempts/` and `/admin/tests/attempts/<attempt_id>/`)
  - 30 new automated tests (78 tests passing in total)
- [x] **Phase 4: Analytics and Reporting Implementation (Completed)**
  - Executive Administrator Analytics Dashboard with real-time database metrics and live filtering by test, status, and date range (`/admin/analytics/dashboard/`)
  - Six interactive, responsive Chart.js visualisations: Daily Attempts Timeline, Pass/Fail Distribution, Average Score by Assessment, Score Distribution Histograms, Topic-Wise Competency, and Assessment Pipeline Funnels
  - Test Summary Reports with cohort metrics, score distributions, and individual test deep dives (`/admin/analytics/tests/` and `/admin/analytics/tests/<test_id>/`)
  - Candidate Performance Reports with multi-field filtering, pagination, and cohort percentiles (`/admin/analytics/candidates/`)
  - Question-Level Item Discrimination Reports with strict assigned-attempt accuracy denominators (`/admin/analytics/questions/`)
  - Topic-Wise Performance & Improvement Reports with proficiency classifications (`/admin/analytics/topics/`)
  - Test Completion and Attempt-Pattern Reports with mutually exclusive funnel categorization and activity audit logs (`/admin/analytics/completion/`)
  - Standard competition ranking and symmetric percentile formula ($\frac{B + 0.5 \times E}{N} \times 100$)
  - Official Candidate Scorecard PDF Export powered by ReportLab with strict answer-key confidentiality (`/test/results/<attempt_id>/pdf/`)
  - 5 Batch CSV Exports with comprehensive spreadsheet formula injection protection (`=`, `+`, `-`, `@`, `\t`, `\r`)
  - 21 new automated tests (99 tests passing in total)
- [x] **Phase 5: Production Hardening, Deployment & Final Verification (Completed)**
  - Dual database support: seamless environment-based switching between SQLite (local development) and PostgreSQL 16 (production) via `dj-database-url` and `psycopg2-binary`
  - Automated database migration readiness with 100% constraint, UUID, and transaction compatibility
  - Complete Docker containerization: multi-stage `Dockerfile`, security-hardened non-root user (`hirescan`), `.dockerignore`, and orchestration via `docker-compose.yml`
  - Production Gunicorn WSGI application server with worker threading, request timeout limits, and structured 12-factor stdout/stderr logging
  - Nginx reverse proxy configuration (`nginx/nginx.conf`) with proxy buffering, request size limits (25MB for CSV imports), security headers, and static file caching
  - Static asset pipeline: WhiteNoise integration (`CompressedManifestStaticFilesStorage`) with offline-bundled vendor assets (Chart.js 4.4, Bootstrap 5.3, Bootstrap Icons) eliminating external CDN reliance
  - Production security hardening: `DEBUG=False` guard, HTTPS cookie flags (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`), HSTS policies, `SECURE_PROXY_SSL_HEADER`, and clickjacking protection (`X_FRAME_OPTIONS = 'DENY'`)
  - Automated health check endpoints (`/health/` and `/healthz/`) with active database ping and latency reporting for load balancers
  - Structured application logging configuration for Django, authentication, assessments, attempts, and analytics
  - Documented SQLite-to-PostgreSQL data migration procedure with natural foreign keys and zero data loss
  - 12 new automated deployment and production hardening tests (111 tests passing in total)

---

## 10. Analytics & Reporting Architecture (Phase 4)

### Metric Definitions & Denominators

| Metric | Denominator | Definition / Mathematical Formula |
| :--- | :--- | :--- |
| **Pass Rate** | Finalized Attempts | $\frac{\text{Passed Finalized Attempts}}{\text{Finalized Attempts (Completed + Timed Out)}} \times 100$ |
| **Completion Rate** | Total Test Registrations | $\frac{\text{Finalized Attempts}}{\text{Total Test Registrations}} \times 100$ |
| **Question Accuracy** | Assigned Finalized Occurrences | $\frac{\text{Correct Responses}}{\text{Attempts where Question was Assigned and Finalized}} \times 100$ *(Note: Total registrations or bank size is NOT used)* |
| **Candidate Percentile** | Test Cohort Size ($N$) | $\frac{B + 0.5 \times E}{N} \times 100$ *(where $B$ is strictly lower scores, $E$ is tied scores)* |
| **Candidate Rank** | Test Cohort Size ($N$) | Standard competition ranking: $1 + \text{Count}(s > s_{\text{cand}})$ with deterministic secondary ordering |

### Security & Compliance Controls
1. **Spreadsheet Formula Injection Defense:** All exported CSV cells are scrubbed; any values starting with `=`, `+`, `-`, `@`, `\t`, or `\r` are prepended with an apostrophe `'` to prevent remote command execution in Microsoft Excel and LibreOffice Calc.
2. **Answer Key Confidentiality:** Candidate-facing scorecards and exported PDFs display topic competency and performance metrics, but strictly withhold correct answer keys to maintain question bank integrity.
3. **Strict Authorization:** All reporting and export endpoints require authenticated administrator sessions (`@admin_required`); candidate PDF downloads verify ownership (`candidate_id`) on the server.
4. **Read-Only Reporting:** All reporting calculations operate purely as read-only queries (`select_related`, `prefetch_related`, `aggregate`) without mutating historical scores or attempts.

---

## 11. Local Development Guide

### Prerequisites
- Python 3.10 to 3.12 (Tested on Python 3.12)
- Git

### Step-by-Step Setup
1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd HireScan
   ```
2. **Create and activate a virtual environment:**
   ```bash
   # On Windows (PowerShell):
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # On Linux / macOS:
   python3 -m venv venv
   source venv/bin/activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   *(For local development, the default `.env.example` settings with `DEBUG=True` and SQLite work out of the box).*
5. **Run database migrations:**
   ```bash
   python manage.py migrate
   ```
6. **Provision an initial administrator account:**
   ```bash
   python manage.py create_admin --email admin@hirescan.local --name "Administrator" --password "AdminPass123!"
   ```
7. **Run the automated test suite:**
   ```bash
   python manage.py test
   ```
8. **Start the local development server:**
   ```bash
   python manage.py runserver
   ```
   Open `http://127.0.0.1:8000/` in your browser.

---

## 12. Production Deployment Guide (Docker & PostgreSQL)

### Deployment Architecture
HireScan in production runs as a 3-tier containerized stack managed via Docker Compose:
- **Nginx (Reverse Proxy):** Terminates client HTTP/HTTPS requests, enforces request size limits (25MB), serves static assets and media directly with gzip and aggressive caching, and proxies dynamic requests to Gunicorn.
- **Web (Django + Gunicorn):** Python 3.12 Debian-slim container running as a non-root user (`hirescan`), serving dynamic routes with 3 worker threads, WhiteNoise static fallback, and database connection pooling.
- **Database (PostgreSQL 16):** Alpine PostgreSQL container with named persistent volume (`hirescan_postgres_data`) and automatic health checks.

### Production Prerequisites
- Docker Engine 24.0+ and Docker Compose v2.20+
- A valid domain name pointing to your host server IP
- TLS Certificate (e.g., Let's Encrypt / Certbot or cloud load balancer)

### Step 1: Configure Production Environment Variables
Create a production `.env` file on your server (never commit this to version control):
```bash
# 1. Generate a strong, random 50+ character SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"

# 2. Populate .env with production parameters:
SECRET_KEY=<paste-generated-key-here>
DEBUG=False
ALLOWED_HOSTS=hirescan.yourdomain.com,web,localhost

CSRF_TRUSTED_ORIGINS=https://hirescan.yourdomain.com
USE_X_FORWARDED_HOST=True
USE_X_FORWARDED_PORT=True

# Reverse proxy protocol headers (if TLS terminates at Nginx or AWS ALB):
SECURE_PROXY_SSL_HEADER=True
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Database Configuration (matches docker-compose.yml):
DB_ENGINE=postgresql
DB_NAME=hirescan_db
DB_USER=hirescan_user
DB_PASSWORD=<generate-strong-db-password>
DB_HOST=db
DB_PORT=5432
DB_CONN_MAX_AGE=600

# Live SMTP Configuration for Candidate OTPs:
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=<your-smtp-api-key>
DEFAULT_FROM_EMAIL=HireScan Assessments <noreply@yourdomain.com>
```

### Step 2: Build and Start Services
```bash
# Build images and start containers in the background
docker compose up -d --build

# Verify all containers are running and healthy
docker compose ps
```

### Step 3: Verify Health Probe
```bash
curl -f http://localhost/health/
# Expected response: {"status": "healthy", "database": "connected", "db_latency_ms": 3.2, ...}
```

### Step 4: Create the Production Administrator Account
Run the interactive CLI command inside the running web container:
```bash
docker compose exec web python manage.py create_admin --email admin@yourdomain.com --name "System Administrator"
```

### Step 5: Common Operational Commands
```bash
# View live application logs:
docker compose logs -f web

# View Nginx access & error logs:
docker compose logs -f nginx

# Restart application service gracefully:
docker compose restart web

# Stop all services:
docker compose down

# Stop all services and remove volumes (CAUTION: removes database volume):
docker compose down -v
```

---

## 13. Database Backup, Restore & Migration Guide

### 1. SQLite to PostgreSQL Migration Procedure
To safely migrate historical assessment data from a development SQLite database to production PostgreSQL without data loss:

1. **Back up the existing SQLite database:**
   ```bash
   cp db.sqlite3 db.sqlite3.backup_$(date +%Y%m%d_%H%M%S)
   ```
2. **Export data to JSON (excluding auto-generated content types):**
   ```bash
   python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes --indent 2 -o hirescan_export.json
   ```
3. **Configure PostgreSQL in `.env`:**
   ```ini
   DB_ENGINE=postgresql
   DB_NAME=hirescan_db
   DB_USER=hirescan_user
   DB_PASSWORD=your_secure_db_password
   DB_HOST=localhost
   DB_PORT=5432
   ```
4. **Apply migrations to the target PostgreSQL database:**
   ```bash
   python manage.py migrate
   ```
5. **Load the exported data into PostgreSQL:**
   ```bash
   python manage.py loaddata hirescan_export.json
   ```
6. **Verify record counts and database integrity:**
   ```bash
   python manage.py shell -c "
   from accounts.models import Admin, Candidate, ActivityLog
   from assessments.models import Test, Question, TestRegistration
   from attempts.models import TestAttempt, AttemptQuestion
   print('Admins:', Admin.objects.count())
   print('Candidates:', Candidate.objects.count())
   print('Tests:', Test.objects.count())
   print('Questions:', Question.objects.count())
   print('Registrations:', TestRegistration.objects.count())
   print('Attempts:', TestAttempt.objects.count())
   print('Assigned Questions:', AttemptQuestion.objects.count())
   "
   ```
7. **Perform an end-to-end smoke test:**
   - Log into `/admin/login/` with the administrator account.
   - Verify candidate rosters, question banks, and registrations.
   - Verify that completed attempt scorecards and analytics charts match the historical SQLite state.
   - Retain the `db.sqlite3.backup_*` file as a permanent offline archive.

### 2. Routine PostgreSQL Database Backup (Production)
```bash
# Create a timestamped SQL dump from the running postgres container:
docker compose exec -T db pg_dump -U postgres -d hirescan_db | gzip > "hirescan_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
```

### 3. Routine PostgreSQL Database Restore
```bash
# Decompress and restore a backup into PostgreSQL:
gunzip < hirescan_backup_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d hirescan_db
```

### 4. Application Release & Rollback Procedure
- **Deploying an Update:**
  ```bash
  git pull origin master
  docker compose build web
  docker compose up -d web
  ```
  *(The `entrypoint.sh` script automatically runs `migrate` and `collectstatic` on container startup).*
- **Rolling Back an Update:**
  ```bash
  git checkout <previous-commit-hash>
  docker compose build web
  docker compose up -d web
  ```


