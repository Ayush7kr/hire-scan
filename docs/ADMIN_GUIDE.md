# HireScan — Administrator Operations & Management Guide

Welcome to the comprehensive administrator operations guide for **HireScan — Test Management Tool**. This guide details every facet of the administrator portal, from initial sign-in and candidate roster onboarding to test authoring, question bank curation, assessment scheduling, and deep analytical evaluation.

---

## Table of Contents
1. [Administrative Sign-In & Access Control](#1-administrative-sign-in--access-control)
2. [Executive Dashboard & Live Audit Stream](#2-executive-dashboard--live-audit-stream)
3. [Candidate Roster & Bulk CSV Import](#3-candidate-roster--bulk-csv-import)
4. [Assessment Management & Test Creation](#4-assessment-management--test-creation)
5. [Question Bank Management & Bulk Import](#5-question-bank-management--bulk-import)
6. [Candidate Registrations & Scheduling](#6-candidate-registrations--scheduling)
7. [Granular Attempt Review & Scorecards](#7-granular-attempt-review--scorecards)
8. [Executive Analytics & Reporting Suite](#8-executive-analytics--reporting-suite)
   - [8.1 Test Summary Benchmarks](#81-test-summary-benchmarks)
   - [8.2 Candidate Performance Directory](#82-candidate-performance-directory)
   - [8.3 Question Item & Difficulty Analysis](#83-question-item--difficulty-analysis)
   - [8.4 Topic Competency Breakdown](#84-topic-competency-breakdown)
   - [8.5 Candidate Funnel & Completion Pipeline](#85-candidate-funnel--completion-pipeline)

---

## 1. Administrative Sign-In & Access Control

The HireScan Administrator Portal is isolated from public candidate access. Administrators authenticate with email/username and password using PBKDF2 cryptographic hashing and secure HTTP-only session cookies.

![HireScan Admin Login](screenshots/04_admin_login.png)

### Key Authentication Features
- **URL Endpoint:** `/admin/login/`
- **Security Protections:** Strict CSRF validation, HTTP-only session cookies, session fixation rotation upon sign-in.
- **Provisioning:** Administrator accounts cannot be created publicly; they must be provisioned via the secure CLI command:
  ```bash
  python manage.py create_admin --email admin@hirescan.io --name "System Admin" --password "YourStrongPassword"
  ```
- **Session Management:** Administrators can securely terminate sessions at any time using the header Sign Out control.

---

## 2. Executive Dashboard & Live Audit Stream

Once authenticated, administrators land on the **Executive Dashboard**, providing an immediate high-level overview of system metrics and a dedicated, independently scrollable audit activity stream.

![Admin Executive Dashboard](screenshots/05_admin_dashboard.png)

### Dashboard Components
1. **Executive KPI Cards:**
   - **Active Tests:** Real-time tally of examinations currently open for candidate attempts.
   - **Total Candidates:** Number of examinees registered in the system roster.
   - **Test Registrations:** Total assessment assignments across all tests.
   - **Completed Attempts:** Evaluated candidate submissions ready for review.
2. **Independent Audit Activity Stream:**
   - Positioned on the right panel, this container has a fixed height with an independent vertical scrollbar.
   - Captures real-time actions: Candidate imports, test status toggles, registration updates, and evaluation finalizations.
   - Avoids page-lengthening sprawl and lets administrators audit historical activities without scrolling away from primary metrics.
3. **Quick Navigation Shortcuts:** One-click links to create new tests, import candidates, register examinees, or download performance reports.

---

## 3. Candidate Roster & Bulk CSV Import

### 3.1 Candidate Directory
The Candidate Directory (`/admin/candidates/`) lists all candidates imported into the system.

![Candidate Roster](screenshots/06_candidate_roster.png)

- **Search & Filter:** Search candidates instantly by name or email.
- **Status Controls:** Toggle candidate status between **Active** and **Inactive** with a single click. Inactive candidates cannot request OTPs or start assessments.
- **Candidate Details:** View assigned tests, historical attempts, and contact information.

### 3.2 Bulk CSV Import Wizard
Administrators can onboard dozens or hundreds of candidates simultaneously via the CSV Import Wizard (`/admin/candidates/import/`).

![Candidate CSV Import Wizard](screenshots/07_candidate_import.png)

#### CSV Format Specification
| Column Header | Requirement | Format / Validation | Description |
| :--- | :--- | :--- | :--- |
| `name` | Required | Plain text (1-200 chars) | Full legal name of the candidate |
| `email` | Required | Valid RFC email | Unique email address used for OTP authentication |
| `phone` | Optional | E.164 or digits (e.g., +1234567890) | Contact telephone number |
| `college` | Optional | Plain text (1-200 chars) | University, institution, or organization |

#### Import Processing & Validation Rules
- **Atomic Processing:** The entire file is validated row-by-row before database commitment.
- **Deduplication:** Existing candidates with matching emails can be either updated or skipped according to import options.
- **Error Recovery:** If any row fails validation (e.g., malformed email or missing name), a detailed error report CSV is immediately downloadable, detailing the exact row number and failure cause.

---

## 4. Assessment Management & Test Creation

### 4.1 Assessment Roster
The Tests Roster (`/admin/tests/`) displays all configured technical assessments.

![Tests Roster](screenshots/08_tests_roster.png)

- **Status Badge:** Visual indicator showing whether the assessment is **Draft/Inactive** or **Published/Active**.
- **Question Sufficiency Rule:** Tests **cannot be activated** unless the question bank contains at least `total_questions`. If an administrator attempts to activate an under-resourced test, the system prevents activation and alerts the user.
- **Actions:** Quick links to manage questions, view candidate attempts, edit test parameters, or toggle publication.

### 4.2 Test Creation Wizard
Creating a new assessment (`/admin/tests/create/`) involves defining testing parameters:

![Test Creation Wizard](screenshots/09_test_creation_wizard.png)

- **Test Name & Description:** Descriptive title and instructions displayed to candidates prior to launching.
- **Duration (Minutes):** Enforced assessment countdown timer.
- **Total Questions:** Number of questions randomly assigned to each candidate from the question bank.
- **Passing Marks:** Minimum score required to achieve a passing grade.
- **Initial Status:** Defaulted to Inactive until questions are populated.

---

## 5. Question Bank Management & Bulk Import

### 5.1 Question Bank
Each test possesses its own dedicated Question Bank (`/admin/tests/<test_id>/questions/`).

![Question Bank Management](screenshots/16_question_bank_list.png)

- **Question Details:** Supports 4-option multiple choice questions (MCQ).
- **Topic Categorization:** Assign questions to specific skills or domains (e.g., Python, SQL, Architecture, Algorithms).
- **Difficulty Grading:** Mark questions as Easy, Medium, or Hard for balanced candidate evaluations.
- **Improvement Suggestions:** Feedback hints linked to specific questions that automatically populate candidate scorecards if the question is missed.

### 5.2 Bulk Question CSV Import
Administrators can rapidly populate question banks using the Question CSV Import tool (`/admin/tests/<test_id>/questions/import/`).

![Question CSV Import Wizard](screenshots/18_question_import_wizard.png)

- **Template Download:** Pre-formatted CSV template available with a single click.
- **Columns:** `question_text`, `option1`, `option2`, `option3`, `option4`, `correct_option` (1-4), `topic`, `difficulty`, `suggestions`.
- **Integrity Guarantee:** Correct options are validated to ensure they map to numbers 1 through 4.

---

## 6. Candidate Registrations & Scheduling

The Registrations module (`/admin/registrations/`) bridges candidates and active assessments.

![Candidate Registrations Roster](screenshots/10_test_registrations.png)

- **Single or Bulk Registration:** Register candidates individually or by cohort to any active assessment.
- **Uniqueness Constraint:** A candidate can only be registered once per test, preventing duplicate attempts.
- **Lifecycle Tracking:** Displays registration status (`registered`, `in_progress`, `completed`, `cancelled`).

---

## 7. Granular Attempt Review & Scorecards

When a candidate completes an assessment, administrators can inspect the full submission record (`/admin/tests/attempts/<attempt_id>/`).

![Candidate Attempt Detail](screenshots/17_candidate_attempt_detail.png)

### Attempt Review Details
- **Candidate Metadata:** Name, email, registration timestamp, start and completion timestamps.
- **Performance Summary:** Total score, percentage, passing status, and duration taken.
- **Question-by-Question Audit:**
  - Question text, assigned topic, and difficulty level.
  - Selected option vs. correct option.
  - Autosave timestamps and response latency.
- **PDF Scorecard Export:** Generate and download an executive, branded PDF scorecard directly from the portal.

---

## 8. Executive Analytics & Reporting Suite

The HireScan Analytics Suite delivers data-driven hiring insights across five dedicated reporting modules.

### 8.1 Test Summary Benchmarks
Navigate to `/admin/analytics/tests/` for cohort-level metrics across all tests.

![Test Summary Analytics](screenshots/11_analytics_test_summaries.png)

- **Metrics Displayed:** Total registrations, completed attempts, pass rate percentage, average score, median score, and standard deviation.
- **Cohort Comparisons:** Compare performance across different examination batches.

### 8.2 Candidate Performance Directory
Navigate to `/admin/analytics/candidates/` for examinee rankings.

![Candidate Performance Analytics](screenshots/12_analytics_candidate_performance.png)

- **Detailed Candidate Ranks:** Sortable by score, percentage, completion speed, and submission timestamp.
- **Filter by Test:** Filter rankings by specific technical assessment.

### 8.3 Question Item & Difficulty Analysis
Navigate to `/admin/analytics/questions/` for item-response psychometric evaluation.

![Question Item Analysis](screenshots/13_analytics_question_analysis.png)

- **Accuracy Rate (%):** Percentage of candidates who answered each question correctly.
- **Difficulty Classification:** Flags questions that are statistically too easy (>90% accuracy) or excessively difficult (<20% accuracy).
- **Discrimination Index:** Identifies whether top-performing candidates answered correctly compared to lower-performing candidates.

### 8.4 Topic Competency Breakdown
Navigate to `/admin/analytics/topics/` to identify skill gaps.

![Topic Competency Breakdown](screenshots/14_analytics_topic_competency.png)

- **Topic Radar & Bar Breakdown:** Performance categorized by technical subject (e.g., Django, Python Core, Algorithms, SQL).
- **Curriculum & Hiring Insights:** Pinpoint specific domain strengths and weaknesses across candidate pools.

### 8.5 Candidate Funnel & Completion Pipeline
Navigate to `/admin/analytics/completion/` for recruitment pipeline velocity.

![Assessment Completion Pipeline](screenshots/15_analytics_completion_pipeline.png)

- **Funnel Stages:** Registered $\rightarrow$ Assessment Launched $\rightarrow$ Questions Autosaved $\rightarrow$ Finalized Submission.
- **Drop-off Analysis:** Detect candidate abandonment rates or technical timeouts.

---

## Summary of Administrator URLs

| Module | URL | Description |
| :--- | :--- | :--- |
| **Login** | `/admin/login/` | Secure administrator authentication |
| **Dashboard** | `/admin/dashboard/` | KPI cards and live audit activity stream |
| **Candidates** | `/admin/candidates/` | Candidate directory and status management |
| **Candidate Import** | `/admin/candidates/import/` | CSV batch candidate onboarding |
| **Tests** | `/admin/tests/` | Assessment configurations and question banks |
| **Test Create** | `/admin/tests/create/` | New assessment creation wizard |
| **Registrations** | `/admin/registrations/` | Assessment scheduling and enrollment |
| **Test Summaries** | `/admin/analytics/tests/` | Cohort benchmarks and pass rates |
| **Candidate Analytics** | `/admin/analytics/candidates/` | Candidate scoring leaderboards |
| **Question Analytics** | `/admin/analytics/questions/` | Item difficulty and discrimination analysis |
| **Topic Analytics** | `/admin/analytics/topics/` | Domain and skill competency breakdown |
| **Completion Pipeline** | `/admin/analytics/completion/` | Candidate progression and drop-off funnel |
