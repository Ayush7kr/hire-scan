"""
Candidate management and CSV import views.
All endpoints require administrator authorization.
No Django Forms or ModelForms used — explicit validation applied.
"""

import csv
import io
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from django.views.decorators.http import require_http_methods

from accounts.decorators import admin_required
from accounts.models import Candidate, ActivityLog
from assessments.models import Test, TestRegistration


@admin_required
def candidate_list(request):
    """
    Display a paginated, searchable list of candidates.
    Supports filtering by active / inactive status and preserving query parameters across pagination.
    Uses database annotation for registration count to prevent N+1 queries.
    """
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip().lower()

    candidates_qs = Candidate.objects.annotate(
        reg_count=Count('registrations')
    ).order_by('-created_at')

    if search_query:
        candidates_qs = candidates_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(whatsapp_number__icontains=search_query) |
            Q(college_name_address__icontains=search_query)
        )

    if status_filter == 'active':
        candidates_qs = candidates_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        candidates_qs = candidates_qs.filter(is_active=False)

    paginator = Paginator(candidates_qs, 15)  # 15 candidates per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Preserve GET parameters across pagination links
    params = request.GET.copy()
    if 'page' in params:
        del params['page']
    query_string = params.urlencode()

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'query_string': query_string,
        'total_count': candidates_qs.count(),
    }
    return render(request, 'admin_portal/candidates/list.html', context)


@admin_required
def candidate_detail(request, candidate_id):
    """
    View a candidate's profile information and registration history.
    """
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    registrations = TestRegistration.objects.filter(
        candidate=candidate
    ).select_related('test').prefetch_related('attempt').order_by('-registered_at')

    # Prepare attempt details
    reg_data = []
    for reg in registrations:
        attempt = getattr(reg, 'attempt', None)
        try:
            attempt = reg.attempt
        except Exception:
            attempt = None
        reg_data.append({
            'registration': reg,
            'test': reg.test,
            'attempt': attempt,
        })

    context = {
        'candidate': candidate,
        'reg_data': reg_data,
    }
    return render(request, 'admin_portal/candidates/detail.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def candidate_edit(request, candidate_id):
    """
    Edit candidate profile details with explicit server-side validation.
    Email uniqueness is enforced against other candidates.
    """
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        whatsapp = request.POST.get('whatsapp_number', '').strip()
        college = request.POST.get('college_name_address', '').strip()
        qualification = request.POST.get('qualification', '').strip()
        passing_year_raw = request.POST.get('passing_year', '').strip()
        other_details = request.POST.get('other_details', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        # Validation
        if not name:
            errors['name'] = 'Candidate name is required.'
        elif len(name) > 150:
            errors['name'] = 'Name cannot exceed 150 characters.'

        if not email:
            errors['email'] = 'Email is required.'
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors['email'] = 'Invalid email address format.'

            # Check uniqueness against other candidates
            if Candidate.objects.filter(email=email).exclude(candidate_id=candidate.candidate_id).exists():
                errors['email'] = 'A candidate with this email address already exists.'

        passing_year = None
        if passing_year_raw:
            try:
                py = int(passing_year_raw)
                if py < 1950 or py > 2100:
                    errors['passing_year'] = 'Passing year must be between 1950 and 2100.'
                else:
                    passing_year = py
            except ValueError:
                errors['passing_year'] = 'Passing year must be a valid 4-digit number.'

        if not errors:
            candidate.name = name
            candidate.email = email
            candidate.whatsapp_number = whatsapp
            candidate.college_name_address = college
            candidate.qualification = qualification
            candidate.passing_year = passing_year
            candidate.other_details = other_details
            candidate.is_active = is_active
            candidate.save()

            ActivityLog.objects.create(
                admin=request.admin_user,
                candidate=candidate,
                activity_type='candidate_updated',
                activity_details=f'Admin updated candidate profile: {candidate.email}'
            )

            messages.success(request, f'Candidate "{candidate.name}" updated successfully.')
            return redirect('candidate_detail', candidate_id=candidate.candidate_id)

    context = {
        'candidate': candidate,
        'errors': errors,
    }
    return render(request, 'admin_portal/candidates/edit.html', context)


@admin_required
@require_http_methods(["POST"])
def candidate_toggle_active(request, candidate_id):
    """
    Safely activate/deactivate a candidate.
    Preserves all historical test records and attempts.
    """
    candidate = get_object_or_404(Candidate, candidate_id=candidate_id)
    candidate.is_active = not candidate.is_active
    candidate.save()

    status_str = 'activated' if candidate.is_active else 'deactivated'
    ActivityLog.objects.create(
        admin=request.admin_user,
        candidate=candidate,
        activity_type=f'candidate_{status_str}',
        activity_details=f'Admin {status_str} candidate {candidate.email}'
    )
    messages.success(request, f'Candidate "{candidate.name}" has been {status_str}.')
    return redirect('candidate_detail', candidate_id=candidate.candidate_id)


@admin_required
def candidate_template_download(request):
    """
    Provide a downloadable CSV template with expected candidate columns.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="candidate_import_template.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'email',
        'name',
        'whatsapp_number',
        'college_name_address',
        'qualification',
        'passing_year',
        'other'
    ])
    writer.writerow([
        'john.doe@example.com',
        'John Doe',
        '9876543210',
        'City Engineering College, Tech Campus',
        'B.Tech Computer Science',
        '2025',
        'Software Engineer Applicant'
    ])
    writer.writerow([
        'jane.smith@example.com',
        'Jane Smith',
        '9876543211',
        'Apex Institute of Technology',
        'MCA',
        '2024',
        'Full Stack Developer'
    ])
    return response


@admin_required
@require_http_methods(["GET", "POST"])
def candidate_import(request):
    """
    Import candidates from CSV and register them for a selected test.
    Validates headers, emails, passing years, detects in-file duplicates,
    reuses existing candidates, and creates non-duplicate test registrations.
    """
    tests = Test.objects.all().order_by('-created_at')
    errors = []
    summary = None

    if request.method == 'POST':
        test_id = request.POST.get('test_id', '').strip()
        csv_file = request.FILES.get('csv_file')

        # 1. Validate Test selection
        if not test_id:
            messages.error(request, 'Please select an assessment test for this import.')
            return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

        test = get_object_or_404(Test, test_id=test_id)

        # 2. Validate file presence & format
        if not csv_file:
            messages.error(request, 'Please select a CSV file to upload.')
            return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, 'Invalid file format. Please upload a .csv file.')
            return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

        # File size limit: 5MB
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, 'File size exceeds maximum allowed limit (5MB).')
            return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

        try:
            # Decode file content
            file_data = csv_file.read()
            try:
                decoded_file = file_data.decode('utf-8-sig')
            except UnicodeDecodeError:
                decoded_file = file_data.decode('latin-1')

            reader = csv.reader(io.StringIO(decoded_file))
            try:
                headers = next(reader)
            except StopIteration:
                messages.error(request, 'The uploaded CSV file is empty.')
                return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

            # Normalize headers
            headers_clean = [h.strip().lower() for h in headers]

            # Verify required columns: 'email' and 'name' are mandatory
            if 'email' not in headers_clean or 'name' not in headers_clean:
                messages.error(
                    request,
                    "Missing required headers. CSV must include at least 'email' and 'name' columns."
                )
                return render(request, 'admin_portal/candidates/import.html', {'tests': tests})

            # Build column index mapping
            col_map = {col: idx for idx, col in enumerate(headers_clean)}

            # Track metrics
            total_rows = 0
            candidates_created = 0
            candidates_reused = 0
            registrations_created = 0
            duplicates_skipped = 0
            seen_emails_in_file = set()
            row_errors = []

            for row_idx, row in enumerate(reader, start=2):
                if not row or not any(field.strip() for field in row):
                    continue  # skip completely blank rows

                total_rows += 1

                # Extract fields safely
                email = row[col_map['email']].strip().lower() if col_map.get('email') is not None and col_map['email'] < len(row) else ''
                name = row[col_map['name']].strip() if col_map.get('name') is not None and col_map['name'] < len(row) else ''
                whatsapp = row[col_map['whatsapp_number']].strip() if col_map.get('whatsapp_number') is not None and col_map['whatsapp_number'] < len(row) else ''
                college = row[col_map['college_name_address']].strip() if col_map.get('college_name_address') is not None and col_map['college_name_address'] < len(row) else ''
                qualification = row[col_map['qualification']].strip() if col_map.get('qualification') is not None and col_map['qualification'] < len(row) else ''
                passing_year_str = row[col_map['passing_year']].strip() if col_map.get('passing_year') is not None and col_map['passing_year'] < len(row) else ''
                other = ''
                if 'other' in col_map and col_map['other'] < len(row):
                    other = row[col_map['other']].strip()
                elif 'other_details' in col_map and col_map['other_details'] < len(row):
                    other = row[col_map['other_details']].strip()

                # Row validations
                row_error_reasons = []

                if not email:
                    row_error_reasons.append("Email is missing")
                else:
                    try:
                        validate_email(email)
                    except ValidationError:
                        row_error_reasons.append("Invalid email format")

                if not name:
                    row_error_reasons.append("Name is missing")

                # In-file duplicate detection
                if email:
                    if email in seen_emails_in_file:
                        row_error_reasons.append(f"Duplicate email '{email}' within uploaded file")
                    else:
                        seen_emails_in_file.add(email)

                passing_year = None
                if passing_year_str:
                    try:
                        py = int(passing_year_str)
                        if py < 1950 or py > 2100:
                            row_error_reasons.append("Passing year must be between 1950 and 2100")
                        else:
                            passing_year = py
                    except ValueError:
                        row_error_reasons.append("Passing year must be a numeric year")

                if row_error_reasons:
                    row_errors.append({
                        'row': row_idx,
                        'email': email or '(Empty)',
                        'name': name or '(Empty)',
                        'reason': "; ".join(row_error_reasons)
                    })
                    continue

                # Database persistence with atomicity per valid row
                try:
                    with transaction.atomic():
                        # Find or create candidate
                        candidate = Candidate.objects.filter(email=email).first()
                        if candidate:
                            candidates_reused += 1
                            # Preserve existing details (do not overwrite)
                        else:
                            candidate = Candidate.objects.create(
                                name=name,
                                email=email,
                                whatsapp_number=whatsapp,
                                college_name_address=college,
                                qualification=qualification,
                                passing_year=passing_year,
                                other_details=other,
                                is_active=True
                            )
                            candidates_created += 1

                        # Register candidate for test
                        reg, created = TestRegistration.objects.get_or_create(
                            candidate=candidate,
                            test=test,
                            defaults={'status': 'registered'}
                        )
                        if created:
                            registrations_created += 1
                        else:
                            duplicates_skipped += 1

                except Exception as ex:
                    row_errors.append({
                        'row': row_idx,
                        'email': email,
                        'name': name,
                        'reason': f"Database save error: {str(ex)}"
                    })

            # Store errors in session for downloadable error report
            request.session['candidate_import_errors'] = row_errors

            summary = {
                'test_name': test.test_name,
                'total_rows': total_rows,
                'candidates_created': candidates_created,
                'candidates_reused': candidates_reused,
                'registrations_created': registrations_created,
                'duplicates_skipped': duplicates_skipped,
                'invalid_rows': len(row_errors),
                'errors': row_errors,
            }

            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='candidates_imported',
                activity_details=(
                    f"Imported {total_rows} rows for test '{test.test_name}': "
                    f"{candidates_created} created, {candidates_reused} reused, "
                    f"{registrations_created} registered, {len(row_errors)} errors."
                )
            )

            messages.success(
                request,
                f"Candidate import completed: {registrations_created} new registration(s) created."
            )

        except Exception as e:
            messages.error(request, f"Error processing CSV file: {str(e)}")

    context = {
        'tests': tests,
        'summary': summary,
    }
    return render(request, 'admin_portal/candidates/import.html', context)


@admin_required
def candidate_import_error_csv(request):
    """
    Download a CSV file containing rows that failed validation in the last import.
    """
    errors = request.session.get('candidate_import_errors', [])
    if not errors:
        messages.info(request, "No import errors available to download.")
        return redirect('candidate_import')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="candidate_import_errors.csv"'

    writer = csv.writer(response)
    writer.writerow(['row_number', 'email', 'name', 'error_reason'])
    for err in errors:
        writer.writerow([err['row'], err['email'], err['name'], err['reason']])

    return response
