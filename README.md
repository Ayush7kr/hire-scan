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
Ran 78 tests in 34.435s
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
- [ ] **Phase 4: Analytics & Reporting**
  - Topic-wise accuracy computation across cohort
  - Pass/fail distributions & top performers
  - CSV and PDF scorecard export
- [ ] **Phase 5: Production Deployment & Hardening**
  - PostgreSQL adapter configuration
  - Docker containerization & static asset optimization

