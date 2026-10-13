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
  - `candidates/`: Candidate profiles, CSV roster imports, eligibility checks
  - `assessments/`: Tests, question banks, candidate-to-test registrations
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
| `Candidate` | `candidate_id` (UUID) | Examinee records created via admin CSV import with unique email. |
| `Test` | `test_id` (UUID) | Test configurations with duration, question count, and passing threshold. |
| `Question` | `question_id` (UUID) | 4-option MCQs belonging to a test bank with topic, difficulty, and suggestions. |
| `TestRegistration` | `registration_id` (UUID) | Links Candidate to Test. Enforces `UNIQUE(candidate, test)`. |
| `TestAttempt` | `attempt_id` (UUID) | Single attempt per registration via `OneToOneField`. Tracks score and status. |
| `AttemptQuestion` | `aq_id` (UUID) | Assigned question subset per attempt. Enforces `UNIQUE(attempt, question)`. |
| `OTPVerification` | `otp_id` (UUID) | Candidate OTP records with PBKDF2 hash, 5-minute expiry, and max 3 attempts. |
| `ActivityLog` | `activity_id` (UUID) | Audit log for logins, OTP issuances, tests, and administrative actions. |

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

Administrator accounts cannot be registered publicly. To create your first administrator:

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
- **Candidate Login:** `http://127.0.0.1:8000/candidate/login/`
- **Candidate Assessment Portal:** `http://127.0.0.1:8000/test/dashboard/`

> **Note on Candidate Login during Local Testing:**
> When requesting an OTP for a candidate email in local development, check your terminal running `runserver`. Django's console email backend will print the 6-digit OTP code directly to stdout.

---

## 7. Running the Automated Test Suite

HireScan includes comprehensive automated tests validating routes, authentication, database constraints, and session isolation.

Execute the test suite:
```bash
python manage.py test
```

Sample test output:
```
Found 20 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
....................
----------------------------------------------------------------------
Ran 20 tests in 6.416s

OK
Destroying test database for alias 'default'...
```

---

## 8. Development Roadmap

- [x] **Phase 1: Foundation (Completed)**
  - Workspace inspection & approved specification synthesis
  - Django project structure, configuration, and environment handling
  - Full relational schema (Admin, Candidate, Test, Question, Registration, Attempt, AttemptQuestion, OTP, ActivityLog)
  - Public homepage meeting all layout & copy specifications
  - Administrator authentication (email/password with PBKDF2 hashing, session management)
  - Candidate passwordless OTP email authentication (hashed OTP, 5-minute expiry, cooldown)
  - Role-based access control decorators (`@admin_required`, `@candidate_required`)
  - Admin CLI provisioning command (`create_admin`)
  - Automated test suite with 20 passing unit/integration tests
- [ ] **Phase 2: Administration**
  - Candidate CSV batch roster imports with field validation & duplicate checks
  - Assessment configuration (duration, passing marks, question count)
  - Question bank CSV parser with MCQ validation
  - Candidate-to-test registration management
- [ ] **Phase 3: Assessment Engine**
  - Randomized question subset generator
  - Timed test execution interface with autosave and backend timestamp enforcement
  - Resilient submission and server-side evaluation engine
- [ ] **Phase 4: Analytics & Reporting**
  - Topic-wise accuracy computation
  - Pass/fail analytics & top scorers
  - CSV and PDF scorecard export
- [ ] **Phase 5: Production Deployment & Hardening**
  - PostgreSQL adapter configuration
  - Docker containerization & static asset optimization
