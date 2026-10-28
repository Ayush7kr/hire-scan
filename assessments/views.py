"""
Assessment and question bank management views.
All views are protected with @admin_required.
No Django Forms or ModelForms used — explicit validation applied.
"""

import csv
import io
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q, F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.decorators import admin_required
from accounts.models import Candidate, ActivityLog
from assessments.models import Test, Question, TestRegistration, NotificationLog
from assessments.notifications import (
    send_registration_notification,
    send_assessment_available_notifications,
    send_assessment_cancelled_notifications,
)
from analytics.services import sanitize_csv_cell
from attempts.models import TestAttempt



# ─────────────────────────────────────────────────────────────────────────────
# 1. TEST MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def test_list(request):
    """
    List all tests with live database metrics:
    duration, questions, passing marks, bank size, registrations, attempts.
    Supports filtering by the 5 test statuses: Scheduled, Upcoming, In Progress, Completed, Cancelled.
    """
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip().lower()

    tests_qs = Test.objects.annotate(
        bank_count=Count('questions', distinct=True),
        reg_count=Count('registrations', distinct=True),
        completed_count=Count(
            'registrations__attempt',
            filter=Q(registrations__attempt__status='completed'),
            distinct=True
        )
    ).order_by('-created_at')

    if search_query:
        tests_qs = tests_qs.filter(
            Q(test_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    now = timezone.now()
    if status_filter == 'cancelled':
        tests_qs = tests_qs.filter(is_cancelled=True)
    elif status_filter == 'upcoming':
        tests_qs = tests_qs.filter(is_cancelled=False, is_active=True, start_time__gt=now)
    elif status_filter == 'in_progress':
        tests_qs = tests_qs.filter(
            is_cancelled=False,
            is_active=True
        ).filter(
            Q(start_time__isnull=True) | Q(start_time__lte=now)
        ).filter(
            Q(end_time__isnull=True) | Q(end_time__gte=now)
        )
    elif status_filter == 'completed':
        tests_qs = tests_qs.filter(
            is_cancelled=False
        ).filter(
            Q(end_time__isnull=False, end_time__lt=now) |
            (Q(is_active=False) & Q(completed_count__gt=0) & Q(completed_count=F('reg_count')))
        )
    elif status_filter == 'scheduled':
        tests_qs = tests_qs.filter(
            is_cancelled=False
        ).exclude(
            Q(is_active=True, start_time__gt=now)
        ).exclude(
            Q(is_active=True) & (Q(start_time__isnull=True) | Q(start_time__lte=now)) & (Q(end_time__isnull=True) | Q(end_time__gte=now))
        ).exclude(
            Q(end_time__isnull=False, end_time__lt=now)
        )
    elif status_filter == 'active':
        tests_qs = tests_qs.filter(is_active=True, is_cancelled=False)
    elif status_filter == 'inactive':
        tests_qs = tests_qs.filter(is_active=False, is_cancelled=False)

    paginator = Paginator(tests_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Attach sufficiency status
    for test in page_obj:
        test.is_sufficient = test.bank_count >= test.total_questions

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
        'total_count': tests_qs.count(),
    }
    return render(request, 'admin_portal/tests/list.html', context)


@admin_required
def test_detail(request, test_id):
    """
    Detailed test configuration, sufficiency analysis, and related metrics.
    """
    test = get_object_or_404(Test, test_id=test_id)
    bank_count = Question.objects.filter(test=test).count()
    reg_count = TestRegistration.objects.filter(test=test).count()
    completed_attempts = TestAttempt.objects.filter(
        registration__test=test, status='completed'
    ).count()

    # Sufficiency calculation
    is_sufficient = bank_count >= test.total_questions
    recommended_count = test.total_questions * 20
    is_optimal = bank_count >= recommended_count

    # Topic breakdown
    topics = Question.objects.filter(test=test).values('topic').annotate(
        count=Count('question_id')
    ).order_by('-count')

    context = {
        'test': test,
        'bank_count': bank_count,
        'reg_count': reg_count,
        'completed_attempts': completed_attempts,
        'is_sufficient': is_sufficient,
        'recommended_count': recommended_count,
        'is_optimal': is_optimal,
        'topics': topics,
    }
    return render(request, 'admin_portal/tests/detail.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def test_create(request):
    """
    Create a new test configuration with explicit validation.
    Tests start as inactive until question bank sufficiency is satisfied.
    """
    errors = {}

    if request.method == 'POST':
        test_name = request.POST.get('test_name', '').strip()
        description = request.POST.get('description', '').strip()
        duration_raw = request.POST.get('duration_minutes', '').strip()
        total_questions_raw = request.POST.get('total_questions', '').strip()
        passing_marks_raw = request.POST.get('passing_marks', '').strip()

        # Validation
        if not test_name:
            errors['test_name'] = 'Test name is required.'
        elif len(test_name) > 200:
            errors['test_name'] = 'Test name cannot exceed 200 characters.'

        duration = None
        if not duration_raw:
            errors['duration_minutes'] = 'Duration is required.'
        else:
            try:
                duration = int(duration_raw)
                if duration <= 0:
                    errors['duration_minutes'] = 'Duration must be greater than 0 minutes.'
            except ValueError:
                errors['duration_minutes'] = 'Duration must be a valid positive number.'

        total_questions = None
        if not total_questions_raw:
            errors['total_questions'] = 'Total questions per attempt is required.'
        else:
            try:
                total_questions = int(total_questions_raw)
                if total_questions <= 0:
                    errors['total_questions'] = 'Total questions must be greater than 0.'
            except ValueError:
                errors['total_questions'] = 'Total questions must be a valid positive number.'

        passing_marks = None
        if not passing_marks_raw:
            errors['passing_marks'] = 'Passing marks is required.'
        else:
            try:
                passing_marks = int(passing_marks_raw)
                if passing_marks <= 0:
                    errors['passing_marks'] = 'Passing marks must be greater than 0.'
                elif total_questions and passing_marks > total_questions:
                    errors['passing_marks'] = 'Passing marks cannot exceed total questions.'
            except ValueError:
                errors['passing_marks'] = 'Passing marks must be a valid positive number.'

        # Schedule parsing
        start_time_raw = request.POST.get('start_time', '').strip()
        end_time_raw = request.POST.get('end_time', '').strip()

        start_time = None
        if start_time_raw:
            dt = parse_datetime(start_time_raw)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                start_time = dt
            else:
                errors['start_time'] = 'Please enter a valid start date and time.'

        end_time = None
        if end_time_raw:
            dt = parse_datetime(end_time_raw)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                end_time = dt
            else:
                errors['end_time'] = 'Please enter a valid end date and time.'

        if start_time and end_time and end_time <= start_time:
            errors['end_time'] = 'End time must be after start time.'

        if not errors:
            test = Test.objects.create(
                test_name=test_name,
                description=description,
                duration_minutes=duration,
                total_questions=total_questions,
                passing_marks=passing_marks,
                start_time=start_time,
                end_time=end_time,
                is_active=False  # starts inactive until bank is uploaded
            )

            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='test_created',
                activity_details=f"Admin created test '{test.test_name}' ({test.total_questions} Qs, {test.duration_minutes}m)."
            )

            messages.success(
                request,
                f"Test '{test.test_name}' created successfully. Now upload question bank to activate it."
            )
            return redirect('test_detail', test_id=test.test_id)

    return render(request, 'admin_portal/tests/create.html', {'errors': errors})


@admin_required
@require_http_methods(["GET", "POST"])
def test_edit(request, test_id):
    """
    Edit test configuration.
    Protects historical integrity if attempts already exist.
    """
    test = get_object_or_404(Test, test_id=test_id)
    attempt_count = TestAttempt.objects.filter(registration__test=test).count()
    errors = {}

    if request.method == 'POST':
        test_name = request.POST.get('test_name', '').strip()
        description = request.POST.get('description', '').strip()
        duration_raw = request.POST.get('duration_minutes', '').strip()
        total_questions_raw = request.POST.get('total_questions', '').strip()
        passing_marks_raw = request.POST.get('passing_marks', '').strip()

        if not test_name:
            errors['test_name'] = 'Test name is required.'

        duration = None
        try:
            duration = int(duration_raw)
            if duration <= 0:
                errors['duration_minutes'] = 'Duration must be greater than 0.'
        except ValueError:
            errors['duration_minutes'] = 'Duration must be a valid positive number.'

        total_questions = None
        try:
            total_questions = int(total_questions_raw)
            if total_questions <= 0:
                errors['total_questions'] = 'Total questions must be greater than 0.'
        except ValueError:
            errors['total_questions'] = 'Total questions must be a valid positive number.'

        passing_marks = None
        try:
            passing_marks = int(passing_marks_raw)
            if passing_marks <= 0:
                errors['passing_marks'] = 'Passing marks must be greater than 0.'
            elif total_questions and passing_marks > total_questions:
                errors['passing_marks'] = 'Passing marks cannot exceed total questions.'
        except ValueError:
            errors['passing_marks'] = 'Passing marks must be a valid positive number.'

        # Schedule parsing
        start_time_raw = request.POST.get('start_time', '').strip()
        end_time_raw = request.POST.get('end_time', '').strip()
        is_cancelled = request.POST.get('is_cancelled') in ['1', 'true', 'on', True]

        start_time = None
        if start_time_raw:
            dt = parse_datetime(start_time_raw)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                start_time = dt
            else:
                errors['start_time'] = 'Please enter a valid start date and time.'

        end_time = None
        if end_time_raw:
            dt = parse_datetime(end_time_raw)
            if dt:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                end_time = dt
            else:
                errors['end_time'] = 'Please enter a valid end date and time.'

        if start_time and end_time and end_time <= start_time:
            errors['end_time'] = 'End time must be after start time.'

        # If test is currently active, ensure question bank satisfies new total questions
        bank_count = Question.objects.filter(test=test).count()
        if test.is_active and total_questions and bank_count < total_questions:
            errors['total_questions'] = (
                f"Cannot set {total_questions} questions: bank only has {bank_count} questions. "
                "Deactivate test first or upload more questions."
            )

        if not errors:
            test.test_name = test_name
            test.description = description
            test.duration_minutes = duration
            test.total_questions = total_questions
            test.passing_marks = passing_marks
            test.start_time = start_time
            test.end_time = end_time
            test.is_cancelled = is_cancelled
            if is_cancelled:
                test.is_active = False
            test.save()

            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='test_updated',
                activity_details=f"Admin updated test '{test.test_name}' configuration."
            )

            messages.success(request, f"Test '{test.test_name}' updated successfully.")
            return redirect('test_detail', test_id=test.test_id)

    context = {
        'test': test,
        'attempt_count': attempt_count,
        'errors': errors,
    }
    return render(request, 'admin_portal/tests/edit.html', context)


@admin_required
@require_http_methods(["POST"])
def test_toggle_status(request, test_id):
    """
    Toggle test active/inactive status via POST.
    Enforces the rule: A test cannot be activated unless bank has at least total_questions questions.
    """
    test = get_object_or_404(Test, test_id=test_id)

    if test.is_cancelled:
        messages.error(
            request,
            f"Cannot activate '{test.test_name}': Test is cancelled. Please uncancel the test first."
        )
        return redirect('test_detail', test_id=test.test_id)

    if not test.is_active:
        # Activation check
        bank_count = Question.objects.filter(test=test).count()
        if bank_count < test.total_questions:
            messages.error(
                request,
                f"Cannot activate '{test.test_name}': Question bank has {bank_count} question(s), "
                f"but {test.total_questions} question(s) are required per attempt."
            )
            return redirect('test_detail', test_id=test.test_id)

        test.is_active = True
        test.save()
        messages.success(request, f"Test '{test.test_name}' is now ACTIVE and available to registered candidates.")
        act_type = 'test_activated'
        # Notify registered candidates of assessment availability
        send_assessment_available_notifications(test, request=request)
    else:
        test.is_active = False
        test.save()
        messages.info(request, f"Test '{test.test_name}' is now INACTIVE. New attempts cannot be started.")
        act_type = 'test_deactivated'

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type=act_type,
        activity_details=f"Admin toggled active status for test '{test.test_name}' to {test.is_active}."
    )
    return redirect('test_detail', test_id=test.test_id)


@admin_required
@require_http_methods(["POST"])
def test_toggle_cancel(request, test_id):
    """
    Cancel or uncancel a test via POST.
    Cancelled tests cannot be upcoming or in progress, and candidates cannot start them.
    """
    test = get_object_or_404(Test, test_id=test_id)

    if not test.is_cancelled:
        test.is_cancelled = True
        test.is_active = False
        test.save()
        messages.warning(request, f"Test '{test.test_name}' has been CANCELLED.")
        ActivityLog.objects.create(
            admin=request.admin_user,
            activity_type='test_cancelled',
            activity_details=f"Admin cancelled test '{test.test_name}'."
        )
        # Notify registered candidates of assessment cancellation
        send_assessment_cancelled_notifications(test, request=request)
    else:
        test.is_cancelled = False
        test.save()
        messages.success(request, f"Test '{test.test_name}' cancellation has been lifted.")
        ActivityLog.objects.create(
            admin=request.admin_user,
            activity_type='test_uncancelled',
            activity_details=f"Admin uncancelled test '{test.test_name}'."
        )
    return redirect('test_detail', test_id=test.test_id)



# ─────────────────────────────────────────────────────────────────────────────
# 2. QUESTION BANK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def question_list(request, test_id):
    """
    List questions in a test's question bank with search, topic/difficulty filters,
    and sufficiency progress bar.
    """
    test = get_object_or_404(Test, test_id=test_id)
    search_query = request.GET.get('q', '').strip()
    topic_filter = request.GET.get('topic', '').strip()
    difficulty_filter = request.GET.get('difficulty', '').strip()

    questions_qs = Question.objects.filter(test=test).order_by('created_at')

    if search_query:
        questions_qs = questions_qs.filter(question_text__icontains=search_query)

    if topic_filter:
        questions_qs = questions_qs.filter(topic=topic_filter)

    if difficulty_filter:
        questions_qs = questions_qs.filter(difficulty=difficulty_filter)

    # Distinct topics for filter dropdown
    available_topics = Question.objects.filter(test=test).values_list('topic', flat=True).distinct().order_by('topic')

    paginator = Paginator(questions_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    bank_count = Question.objects.filter(test=test).count()
    is_sufficient = bank_count >= test.total_questions
    recommended_count = test.total_questions * 20

    context = {
        'test': test,
        'page_obj': page_obj,
        'search_query': search_query,
        'topic_filter': topic_filter,
        'difficulty_filter': difficulty_filter,
        'available_topics': available_topics,
        'bank_count': bank_count,
        'is_sufficient': is_sufficient,
        'recommended_count': recommended_count,
    }
    return render(request, 'admin_portal/tests/question_list.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def question_create(request, test_id):
    """
    Add a single question manually to the question bank.
    """
    test = get_object_or_404(Test, test_id=test_id)
    errors = {}

    if request.method == 'POST':
        q_text = request.POST.get('question_text', '').strip()
        opt1 = request.POST.get('option1', '').strip()
        opt2 = request.POST.get('option2', '').strip()
        opt3 = request.POST.get('option3', '').strip()
        opt4 = request.POST.get('option4', '').strip()
        correct_raw = request.POST.get('correct_option', '').strip()
        topic = request.POST.get('topic', '').strip()
        difficulty = request.POST.get('difficulty', 'medium').strip().lower()
        suggestions = request.POST.get('suggestions', '').strip()

        if not q_text:
            errors['question_text'] = 'Question text is required.'
        if not opt1:
            errors['option1'] = 'Option 1 is required.'
        if not opt2:
            errors['option2'] = 'Option 2 is required.'
        if not opt3:
            errors['option3'] = 'Option 3 is required.'
        if not opt4:
            errors['option4'] = 'Option 4 is required.'

        correct_option = None
        try:
            correct_option = int(correct_raw)
            if correct_option not in [1, 2, 3, 4]:
                errors['correct_option'] = 'Correct option must be 1, 2, 3, or 4.'
        except ValueError:
            errors['correct_option'] = 'Correct option must be a number (1-4).'

        if not topic:
            errors['topic'] = 'Topic is required.'

        if difficulty not in ['easy', 'medium', 'hard']:
            difficulty = 'medium'

        # Check duplicate in this test
        if q_text and Question.objects.filter(test=test, question_text__iexact=q_text).exists():
            errors['question_text'] = 'A question with this exact text already exists in this test.'

        if not errors:
            q = Question.objects.create(
                test=test,
                question_text=q_text,
                option1=opt1,
                option2=opt2,
                option3=opt3,
                option4=opt4,
                correct_option=correct_option,
                topic=topic,
                difficulty=difficulty,
                suggestions=suggestions
            )
            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='question_created',
                activity_details=f"Admin added question '{q_text[:50]}' to test '{test.test_name}'."
            )
            messages.success(request, 'Question added successfully to the question bank.')
            return redirect('question_list', test_id=test.test_id)

    return render(request, 'admin_portal/tests/question_create.html', {
        'test': test,
        'errors': errors
    })


@admin_required
@require_http_methods(["GET", "POST"])
def question_edit(request, test_id, question_id):
    """
    Edit an existing question.
    """
    test = get_object_or_404(Test, test_id=test_id)
    question = get_object_or_404(Question, question_id=question_id, test=test)
    errors = {}

    if request.method == 'POST':
        q_text = request.POST.get('question_text', '').strip()
        opt1 = request.POST.get('option1', '').strip()
        opt2 = request.POST.get('option2', '').strip()
        opt3 = request.POST.get('option3', '').strip()
        opt4 = request.POST.get('option4', '').strip()
        correct_raw = request.POST.get('correct_option', '').strip()
        topic = request.POST.get('topic', '').strip()
        difficulty = request.POST.get('difficulty', 'medium').strip().lower()
        suggestions = request.POST.get('suggestions', '').strip()

        if not q_text:
            errors['question_text'] = 'Question text is required.'
        if not opt1:
            errors['option1'] = 'Option 1 is required.'
        if not opt2:
            errors['option2'] = 'Option 2 is required.'
        if not opt3:
            errors['option3'] = 'Option 3 is required.'
        if not opt4:
            errors['option4'] = 'Option 4 is required.'

        correct_option = None
        try:
            correct_option = int(correct_raw)
            if correct_option not in [1, 2, 3, 4]:
                errors['correct_option'] = 'Correct option must be 1, 2, 3, or 4.'
        except ValueError:
            errors['correct_option'] = 'Correct option must be a number (1-4).'

        if not topic:
            errors['topic'] = 'Topic is required.'

        if difficulty not in ['easy', 'medium', 'hard']:
            difficulty = 'medium'

        # Check duplicate
        if q_text and Question.objects.filter(test=test, question_text__iexact=q_text).exclude(question_id=question.question_id).exists():
            errors['question_text'] = 'Another question with this exact text already exists in this test.'

        if not errors:
            question.question_text = q_text
            question.option1 = opt1
            question.option2 = opt2
            question.option3 = opt3
            question.option4 = opt4
            question.correct_option = correct_option
            question.topic = topic
            question.difficulty = difficulty
            question.suggestions = suggestions
            question.save()

            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='question_updated',
                activity_details=f"Admin updated question '{question.question_text[:50]}' in test '{test.test_name}'."
            )

            messages.success(request, 'Question updated successfully.')
            return redirect('question_list', test_id=test.test_id)

    context = {
        'test': test,
        'question': question,
        'errors': errors,
    }
    return render(request, 'admin_portal/tests/question_edit.html', context)


@admin_required
@require_http_methods(["POST"])
def question_delete(request, test_id, question_id):
    """
    Delete a question. If test is active and bank falls below total_questions,
    automatically deactivate test and inform administrator.
    """
    test = get_object_or_404(Test, test_id=test_id)
    question = get_object_or_404(Question, question_id=question_id, test=test)
    q_preview = question.question_text[:50]
    question.delete()

    ActivityLog.objects.create(
        admin=request.admin_user,
        activity_type='question_deleted',
        activity_details=f"Admin deleted question '{q_preview}' from test '{test.test_name}'."
    )

    bank_count = Question.objects.filter(test=test).count()
    if test.is_active and bank_count < test.total_questions:
        test.is_active = False
        test.save()
        messages.warning(
            request,
            f"Question deleted. Test '{test.test_name}' was DEACTIVATED because available questions ({bank_count}) "
            f"fell below configured questions ({test.total_questions})."
        )
    else:
        messages.success(request, "Question deleted successfully.")

    return redirect('question_list', test_id=test.test_id)


@admin_required
def question_template_download(request):
    """
    Download a sample question bank CSV template.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="question_bank_template.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'question',
        'option1',
        'option2',
        'option3',
        'option4',
        'correct_option',
        'topic',
        'difficulty',
        'suggestions'
    ])
    writer.writerow([
        'What is the output of print(type([])) in Python 3?',
        "<class 'list'>",
        "<class 'tuple'>",
        "<class 'array'>",
        "<class 'dict'>",
        '1',
        'Data Types',
        'easy',
        'Review standard built-in container types in Python.'
    ])
    writer.writerow([
        'Which HTTP status code signifies a resource was successfully created?',
        '200 OK',
        '201 Created',
        '204 No Content',
        '301 Moved Permanently',
        '2',
        'Web Standards',
        'medium',
        'Study standard RFC HTTP REST response codes.'
    ])
    return response


@admin_required
@require_http_methods(["GET", "POST"])
def question_import(request, test_id):
    """
    Upload and validate a question bank CSV for a specific test.
    Associates questions strictly with test_id.
    Validates MCQ options, correct_option normalization (1-4 or A-D),
    duplicate questions in file & database, and generates error CSV.
    """
    test = get_object_or_404(Test, test_id=test_id)
    summary = None

    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')

        if not csv_file:
            messages.error(request, 'Please select a CSV file to upload.')
            return render(request, 'admin_portal/tests/question_import.html', {'test': test})

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, 'Invalid file format. Please upload a .csv file.')
            return render(request, 'admin_portal/tests/question_import.html', {'test': test})

        if csv_file.size > 10 * 1024 * 1024:
            messages.error(request, 'File size exceeds maximum allowed limit (10MB).')
            return render(request, 'admin_portal/tests/question_import.html', {'test': test})

        try:
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
                return render(request, 'admin_portal/tests/question_import.html', {'test': test})

            headers_clean = [h.strip().lower() for h in headers]

            # Normalize potential header variations
            # e.g. option_1 -> option1
            normalized_headers = []
            for h in headers_clean:
                if h in ['option_1', 'opt1', 'option 1']:
                    normalized_headers.append('option1')
                elif h in ['option_2', 'opt2', 'option 2']:
                    normalized_headers.append('option2')
                elif h in ['option_3', 'opt3', 'option 3']:
                    normalized_headers.append('option3')
                elif h in ['option_4', 'opt4', 'option 4']:
                    normalized_headers.append('option4')
                elif h in ['correct_answer', 'answer', 'correct']:
                    normalized_headers.append('correct_option')
                elif h in ['question_text']:
                    normalized_headers.append('question')
                else:
                    normalized_headers.append(h)

            col_map = {col: idx for idx, col in enumerate(normalized_headers)}

            # Validate mandatory headers
            required_cols = ['question', 'option1', 'option2', 'option3', 'option4', 'correct_option', 'topic']
            missing = [c for c in required_cols if c not in col_map]
            if missing:
                messages.error(
                    request,
                    f"Missing required CSV column headers: {', '.join(missing)}."
                )
                return render(request, 'admin_portal/tests/question_import.html', {'test': test})

            total_rows = 0
            questions_imported = 0
            duplicate_skipped = 0
            row_errors = []
            seen_questions_in_file = set()

            for row_idx, row in enumerate(reader, start=2):
                if not row or not any(field.strip() for field in row):
                    continue

                total_rows += 1
                q_text = row[col_map['question']].strip() if col_map['question'] < len(row) else ''
                opt1 = row[col_map['option1']].strip() if col_map['option1'] < len(row) else ''
                opt2 = row[col_map['option2']].strip() if col_map['option2'] < len(row) else ''
                opt3 = row[col_map['option3']].strip() if col_map['option3'] < len(row) else ''
                opt4 = row[col_map['option4']].strip() if col_map['option4'] < len(row) else ''
                correct_raw = row[col_map['correct_option']].strip() if col_map['correct_option'] < len(row) else ''
                topic = row[col_map['topic']].strip() if col_map['topic'] < len(row) else ''

                difficulty = 'medium'
                if 'difficulty' in col_map and col_map['difficulty'] < len(row):
                    d_val = row[col_map['difficulty']].strip().lower()
                    if d_val in ['easy', 'medium', 'hard']:
                        difficulty = d_val

                suggestions = ''
                if 'suggestions' in col_map and col_map['suggestions'] < len(row):
                    suggestions = row[col_map['suggestions']].strip()

                row_error_reasons = []

                if not q_text:
                    row_error_reasons.append("Question text is missing")
                if not opt1:
                    row_error_reasons.append("Option 1 is missing")
                if not opt2:
                    row_error_reasons.append("Option 2 is missing")
                if not opt3:
                    row_error_reasons.append("Option 3 is missing")
                if not opt4:
                    row_error_reasons.append("Option 4 is missing")
                if not topic:
                    row_error_reasons.append("Topic is missing")

                # Normalize correct_option
                correct_option = None
                if correct_raw in ['1', '2', '3', '4']:
                    correct_option = int(correct_raw)
                elif correct_raw.upper() in ['A', 'B', 'C', 'D']:
                    mapping = {'A': 1, 'B': 2, 'C': 3, 'D': 4}
                    correct_option = mapping[correct_raw.upper()]
                else:
                    row_error_reasons.append(f"Invalid correct_option '{correct_raw}'; must be 1-4 or A-D")

                # In-file duplicate check
                q_key = q_text.lower()
                if q_text:
                    if q_key in seen_questions_in_file:
                        row_error_reasons.append("Duplicate question text within this CSV file")
                    else:
                        seen_questions_in_file.add(q_key)

                if row_error_reasons:
                    row_errors.append({
                        'row': row_idx,
                        'question': q_text[:50] or '(Empty)',
                        'topic': topic or '(Empty)',
                        'reason': "; ".join(row_error_reasons)
                    })
                    continue

                # Check database duplicate
                if Question.objects.filter(test=test, question_text__iexact=q_text).exists():
                    duplicate_skipped += 1
                    continue

                # Save question
                try:
                    Question.objects.create(
                        test=test,
                        question_text=q_text,
                        option1=opt1,
                        option2=opt2,
                        option3=opt3,
                        option4=opt4,
                        correct_option=correct_option,
                        topic=topic,
                        difficulty=difficulty,
                        suggestions=suggestions
                    )
                    questions_imported += 1
                except Exception as ex:
                    row_errors.append({
                        'row': row_idx,
                        'question': q_text[:50],
                        'topic': topic,
                        'reason': f"Database error: {str(ex)}"
                    })

            # Store errors in session
            request.session['question_import_errors'] = row_errors

            summary = {
                'total_rows': total_rows,
                'imported': questions_imported,
                'duplicates_skipped': duplicate_skipped,
                'invalid_rows': len(row_errors),
                'errors': row_errors,
            }

            ActivityLog.objects.create(
                admin=request.admin_user,
                activity_type='questions_imported',
                activity_details=(
                    f"Imported {questions_imported} questions for test '{test.test_name}' "
                    f"({duplicate_skipped} duplicates skipped, {len(row_errors)} invalid)."
                )
            )

            messages.success(
                request,
                f"Question bank upload complete: {questions_imported} new question(s) added."
            )

        except Exception as e:
            messages.error(request, f"Error processing CSV: {str(e)}")

    context = {
        'test': test,
        'summary': summary,
    }
    return render(request, 'admin_portal/tests/question_import.html', context)


@admin_required
def question_import_error_csv(request):
    """
    Download a CSV file containing rows that failed question validation.
    """
    errors = request.session.get('question_import_errors', [])
    if not errors:
        messages.info(request, "No question import errors available.")
        return redirect('test_list')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="question_import_errors.csv"'

    writer = csv.writer(response)
    writer.writerow(['row_number', 'question', 'topic', 'error_reason'])
    for err in errors:
        writer.writerow([
            err['row'],
            sanitize_csv_cell(err.get('question', '')),
            sanitize_csv_cell(err.get('topic', '')),
            sanitize_csv_cell(err.get('reason', ''))
        ])

    return response


# ─────────────────────────────────────────────────────────────────────────────
# 3. TEST REGISTRATION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def registration_list(request):
    """
    List candidate-to-test registrations with candidate, test, date, status, attempt.
    Supports searching by candidate name, email, or test name, and filtering by test,
    registration status, and attempt status with pagination query preservation.
    """
    search_query = request.GET.get('q', '').strip()
    test_filter = request.GET.get('test_id', '').strip()
    status_filter = request.GET.get('status', '').strip()
    attempt_status = request.GET.get('attempt_status', '').strip()

    regs_qs = TestRegistration.objects.all().select_related(
        'candidate', 'test'
    ).prefetch_related('attempt').order_by('-registered_at')

    if search_query:
        regs_qs = regs_qs.filter(
            Q(candidate__name__icontains=search_query) |
            Q(candidate__email__icontains=search_query) |
            Q(test__test_name__icontains=search_query)
        )

    if test_filter:
        regs_qs = regs_qs.filter(test__test_id=test_filter)

    if status_filter:
        regs_qs = regs_qs.filter(status=status_filter)

    if attempt_status == 'completed':
        regs_qs = regs_qs.filter(attempt__status='completed')
    elif attempt_status == 'in_progress':
        regs_qs = regs_qs.filter(attempt__status='in_progress')
    elif attempt_status == 'not_attempted':
        regs_qs = regs_qs.filter(attempt__isnull=True)

    all_tests = Test.objects.all().order_by('test_name')

    paginator = Paginator(regs_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Attach attempt status
    for reg in page_obj:
        try:
            reg.attempt_obj = reg.attempt
        except Exception:
            reg.attempt_obj = None

    # Preserve GET parameters across pagination links
    params = request.GET.copy()
    if 'page' in params:
        del params['page']
    query_string = params.urlencode()

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'test_filter': test_filter,
        'status_filter': status_filter,
        'attempt_status': attempt_status,
        'all_tests': all_tests,
        'query_string': query_string,
        'total_count': regs_qs.count(),
    }
    return render(request, 'admin_portal/registrations/list.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def registration_create(request):
    """
    Register single or multiple candidates for a test with atomic duplicate prevention.
    Preserves original single-candidate registration while supporting bulk selection.
    """
    candidates = Candidate.objects.filter(is_active=True).order_by('name')
    tests = Test.objects.all().order_by('test_name')
    errors = {}
    selected_mode = request.POST.get('mode', 'single')

    if request.method == 'POST':
        test_id = request.POST.get('test_id', '').strip()
        test = None

        if not test_id:
            errors['test_id'] = 'Please select a test.'
        else:
            try:
                test = Test.objects.get(test_id=test_id)
            except (Test.DoesNotExist, ValueError):
                errors['test_id'] = 'Selected test does not exist.'

        if selected_mode == 'multiple':
            candidate_ids = request.POST.getlist('candidate_ids')
            if not candidate_ids:
                errors['candidate_ids'] = 'Please select at least one candidate.'

            if not errors and test:
                valid_candidates = []
                rejected = []  # list of (identifier/name, reason)
                already_registered = []

                # Validate format and existence
                for cid_raw in candidate_ids:
                    cid_raw = cid_raw.strip()
                    if not cid_raw:
                        continue
                    try:
                        cid = uuid.UUID(cid_raw)
                    except (ValueError, AttributeError):
                        rejected.append((cid_raw, "Malformed candidate ID"))
                        continue

                    try:
                        cand = Candidate.objects.get(candidate_id=cid)
                    except Candidate.DoesNotExist:
                        rejected.append((str(cid), "Candidate does not exist"))
                        continue

                    if not cand.is_active:
                        rejected.append((f"{cand.name} ({cand.email})", "Candidate is inactive"))
                        continue

                    valid_candidates.append(cand)

                if valid_candidates:
                    existing_cand_ids = set(
                        TestRegistration.objects.filter(
                            test=test,
                            candidate__in=valid_candidates
                        ).values_list('candidate_id', flat=True)
                    )

                    to_register = []
                    for cand in valid_candidates:
                        if cand.candidate_id in existing_cand_ids:
                            already_registered.append(cand)
                        else:
                            to_register.append(cand)

                    # Deduplicate in case candidate_ids contained duplicates within the submission
                    unique_to_register = []
                    seen_ids = set()
                    for cand in to_register:
                        if cand.candidate_id not in seen_ids:
                            seen_ids.add(cand.candidate_id)
                            unique_to_register.append(cand)

                    created_candidates = []
                    failed = []
                    if unique_to_register:
                        for cand in unique_to_register:
                            try:
                                with transaction.atomic():
                                    TestRegistration.objects.create(
                                        candidate=cand,
                                        test=test,
                                        status='registered'
                                    )
                                    ActivityLog.objects.create(
                                        admin=request.admin_user,
                                        candidate=cand,
                                        activity_type='candidate_registered',
                                        activity_details=f"Admin registered {cand.email} for test '{test.test_name}' (bulk registration)."
                                    )
                                created_candidates.append(cand)
                            except IntegrityError:
                                # Concurrent registration collision: check if candidate is already registered
                                if TestRegistration.objects.filter(candidate=cand, test=test).exists():
                                    if cand not in already_registered:
                                        already_registered.append(cand)
                                else:
                                    failed.append((f"{cand.name} ({cand.email})", "Database registration conflict"))
                            except Exception as exc:
                                failed.append((f"{cand.name} ({cand.email})", f"Registration error: {str(exc)}"))

                    # Transparent reporting
                    if created_candidates:
                        messages.success(
                            request,
                            f"Successfully registered {len(created_candidates)} candidate(s) for '{test.test_name}'."
                        )
                    elif already_registered and not rejected and not failed:
                        messages.info(
                            request,
                            f"0 new registrations created: All {len(already_registered)} selected candidate(s) were already registered for '{test.test_name}'. Duplicate registrations were prevented."
                        )

                    if already_registered:
                        already_names = ", ".join([f"{c.name} ({c.email})" for c in already_registered[:5]])
                        more_ar = f" and {len(already_registered)-5} more" if len(already_registered) > 5 else ""
                        messages.warning(
                            request,
                            f"{len(already_registered)} candidate(s) were already registered for '{test.test_name}': {already_names}{more_ar}."
                        )

                    if rejected:
                        rej_msgs = "; ".join([f"{name}: {reason}" for name, reason in rejected[:5]])
                        more_rej = f" and {len(rejected)-5} more" if len(rejected) > 5 else ""
                        messages.error(
                            request,
                            f"{len(rejected)} candidate selection(s) were rejected: {rej_msgs}{more_rej}."
                        )

                    if failed:
                        fail_msgs = "; ".join([f"{name}: {reason}" for name, reason in failed[:5]])
                        more_fail = f" and {len(failed)-5} more" if len(failed) > 5 else ""
                        messages.error(
                            request,
                            f"{len(failed)} candidate registration(s) failed: {fail_msgs}{more_fail}."
                        )

                    # Structured bulk summary
                    summary_data = {
                        'test_name': test.test_name,
                        'test_id': str(test.test_id),
                        'total_selected': len([c for c in candidate_ids if c.strip()]),
                        'created_count': len(created_candidates),
                        'created_candidates': [{'name': c.name, 'email': c.email} for c in created_candidates],
                        'already_registered_count': len(already_registered),
                        'already_registered_candidates': [{'name': c.name, 'email': c.email} for c in already_registered],
                        'rejected_count': len(rejected),
                        'rejected_candidates': [{'identifier': name, 'reason': reason} for name, reason in rejected],
                        'failed_count': len(failed),
                        'failed_candidates': [{'identifier': name, 'reason': reason} for name, reason in failed],
                        'error_count': len(failed) + (1 if errors.get('general') else 0),
                        'general_error': errors.get('general', ''),
                    }
                    request.session['bulk_registration_summary'] = summary_data

                    ActivityLog.objects.create(
                        admin=request.admin_user,
                        activity_type='bulk_candidates_registered',
                        activity_details=(
                            f"Admin processed bulk registration for test '{test.test_name}': "
                            f"{len(created_candidates)} newly registered, {len(already_registered)} already registered (duplicates prevented), "
                            f"{len(rejected)} rejected (ineligible), {len(failed)} failed."
                        )
                    )

                    # Dispatched registration emails for newly registered candidates
                    for cand in created_candidates:
                        send_registration_notification(cand, test, request=request)

                    return redirect('registration_bulk_summary')
                elif rejected:
                    rej_msgs = "; ".join([f"{name}: {reason}" for name, reason in rejected[:5]])
                    errors['general'] = f"Selected candidate(s) rejected: {rej_msgs}."

        else:
            # Single candidate registration (strictly preserving original logic and response messages)
            candidate_id = request.POST.get('candidate_id', '').strip()

            if not candidate_id:
                errors['candidate_id'] = 'Please select a candidate.'

            candidate = None
            if candidate_id:
                try:
                    candidate = Candidate.objects.get(candidate_id=candidate_id)
                    if not candidate.is_active:
                        errors['candidate_id'] = 'Selected candidate is inactive.'
                except (Candidate.DoesNotExist, ValueError):
                    errors['candidate_id'] = 'Selected candidate does not exist.'

            if candidate and test:
                # Check duplicate registration
                if TestRegistration.objects.filter(candidate=candidate, test=test).exists():
                    errors['general'] = (
                        f"Candidate '{candidate.name}' ({candidate.email}) is already registered "
                        f"for test '{test.test_name}'."
                    )

            if not errors and candidate and test:
                try:
                    with transaction.atomic():
                        reg = TestRegistration.objects.create(
                            candidate=candidate,
                            test=test,
                            status='registered'
                        )
                        ActivityLog.objects.create(
                            admin=request.admin_user,
                            candidate=candidate,
                            activity_type='candidate_registered',
                            activity_details=f"Admin registered {candidate.email} for test '{test.test_name}'."
                        )
                    # Notify candidate
                    send_registration_notification(candidate, test, request=request)
                    messages.success(
                        request,
                        f"Candidate '{candidate.name}' registered successfully for '{test.test_name}'."
                    )
                    return redirect('registration_list')
                except IntegrityError:
                    errors['general'] = 'Duplicate registration constraint violated.'

    context = {
        'candidates': candidates,
        'tests': tests,
        'errors': errors,
        'selected_mode': selected_mode,
    }
    return render(request, 'admin_portal/registrations/create.html', context)


@admin_required
def registration_bulk_summary(request):
    """
    Display comprehensive post-registration summary report for bulk candidate operations.
    Shows created registrations, duplicate registrations, and validation rejections.
    """
    summary = request.session.get('bulk_registration_summary')
    if not summary:
        messages.info(request, "No recent bulk registration summary found.")
        return redirect('registration_list')

    context = {
        'summary': summary,
    }
    return render(request, 'admin_portal/registrations/bulk_summary.html', context)



@admin_required
def registration_detail(request, registration_id):
    """
    View registration details, candidate information, test specifications, and attempt log.
    """
    reg = get_object_or_404(
        TestRegistration.objects.select_related('candidate', 'test'),
        registration_id=registration_id
    )
    attempt = None
    try:
        attempt = reg.attempt
    except Exception:
        attempt = None

    context = {
        'reg': reg,
        'attempt': attempt,
    }
    return render(request, 'admin_portal/registrations/detail.html', context)


@admin_required
@require_http_methods(["POST"])
def registration_cancel(request, registration_id):
    """
    Cancel an existing registration.
    If the candidate has already completed an attempt, prevent cancellation to protect historical scores.
    """
    reg = get_object_or_404(TestRegistration, registration_id=registration_id)

    # Protect completed attempts
    try:
        if reg.attempt and reg.attempt.status == 'completed':
            messages.error(
                request,
                "Cannot cancel registration: candidate has already completed this assessment."
            )
            return redirect('registration_detail', registration_id=reg.registration_id)
    except Exception:
        pass

    reg.status = 'cancelled'
    reg.save()

    ActivityLog.objects.create(
        admin=request.admin_user,
        candidate=reg.candidate,
        activity_type='registration_cancelled',
        activity_details=f"Admin cancelled registration of {reg.candidate.email} for '{reg.test.test_name}'."
    )
    messages.success(request, "Registration cancelled successfully.")
    return redirect('registration_list')


# ─────────────────────────────────────────────────────────────────────────────
# 4. ATTEMPT INSPECTION (ADMIN)
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def admin_test_attempts(request, test_id):
    """
    List candidate attempts for a specific assessment.
    """
    test = get_object_or_404(Test, test_id=test_id)
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    attempts_qs = TestAttempt.objects.filter(
        registration__test=test
    ).select_related('registration__candidate').order_by('-start_time')

    if search_query:
        attempts_qs = attempts_qs.filter(
            Q(registration__candidate__name__icontains=search_query) |
            Q(registration__candidate__email__icontains=search_query)
        )

    if status_filter:
        attempts_qs = attempts_qs.filter(status=status_filter)

    paginator = Paginator(attempts_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Calculate basic summary metrics
    total_attempts = attempts_qs.count()
    completed_count = attempts_qs.filter(status='completed').count()
    passed_count = attempts_qs.filter(is_passed=True).count()

    context = {
        'test': test,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'total_attempts': total_attempts,
        'completed_count': completed_count,
        'passed_count': passed_count,
    }
    return render(request, 'admin_portal/tests/attempts_list.html', context)


@admin_required
def admin_attempt_detail(request, attempt_id):
    """
    Detailed view of a candidate's attempt for administrators.
    Displays questions, selected answers, correct answers, topic performance, and score metrics.
    """
    from attempts.services import get_topic_performance

    attempt = get_object_or_404(
        TestAttempt.objects.select_related('registration__test', 'registration__candidate'),
        attempt_id=attempt_id
    )

    topic_performance = get_topic_performance(attempt)
    attempt_questions = list(
        attempt.attempt_questions
        .select_related('question')
        .order_by('question_order')
    )

    # Format time taken
    seconds = attempt.time_taken_seconds or 0
    mins = seconds // 60
    secs = seconds % 60
    time_taken_formatted = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    # Preserve calling filter parameters for back-navigation
    return_params = request.GET.copy()
    if 'from' in return_params:
        del return_params['from']
    return_querystring = return_params.urlencode()

    context = {
        'attempt': attempt,
        'test': attempt.registration.test,
        'candidate': attempt.registration.candidate,
        'topic_performance': topic_performance,
        'attempt_questions': attempt_questions,
        'time_taken_formatted': time_taken_formatted,
        'nav_from': request.GET.get('from', '').strip(),
        'return_querystring': return_querystring,
    }
    return render(request, 'admin_portal/tests/attempt_detail.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 5. NOTIFICATION DELIVERY MONITORING & RETRY
# ─────────────────────────────────────────────────────────────────────────────

@admin_required
def notification_list(request):
    """
    Operational notification delivery monitor for administrators.
    Displays dispatch logs, delivery statuses (sent/failed), safe error details,
    and supports searching, filtering, and controlled retry.
    """
    status_filter = request.GET.get('status', '').strip().lower()
    type_filter = request.GET.get('type', '').strip().lower()
    search_query = request.GET.get('q', '').strip()

    notifications_qs = NotificationLog.objects.select_related('candidate', 'test').order_by('-sent_at')

    if status_filter in ['sent', 'failed']:
        notifications_qs = notifications_qs.filter(status=status_filter)

    if type_filter:
        notifications_qs = notifications_qs.filter(notification_type=type_filter)

    if search_query:
        notifications_qs = notifications_qs.filter(
            Q(recipient_email__icontains=search_query) |
            Q(candidate__name__icontains=search_query) |
            Q(test__test_name__icontains=search_query) |
            Q(subject__icontains=search_query)
        )

    # Operational metrics
    total_count = NotificationLog.objects.count()
    sent_count = NotificationLog.objects.filter(status='sent').count()
    failed_count = NotificationLog.objects.filter(status='failed').count()

    paginator = Paginator(notifications_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'admin_user': request.admin_user,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search_query': search_query,
        'total_count': total_count,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'type_choices': NotificationLog.TYPE_CHOICES,
    }
    return render(request, 'admin_portal/registrations/notification_list.html', context)


@admin_required
@require_http_methods(["POST"])
def notification_retry(request, log_id):
    """
    Safely retry a failed notification delivery.
    Enforces authorization, checks candidate/test validity, prevents duplicate
    deliveries, sanitizes error logs, and audits retry operations.
    """
    import re
    log = get_object_or_404(
        NotificationLog.objects.select_related('candidate', 'test'),
        notification_id=log_id
    )

    if log.status == 'sent':
        messages.info(request, f"Notification to {log.recipient_email} has already been sent successfully.")
        return redirect('notification_list')

    # Anti-duplicate protection: check if a successful notification has already been delivered
    already_sent = NotificationLog.objects.filter(
        candidate=log.candidate,
        test=log.test,
        notification_type=log.notification_type,
        status='sent'
    ).exists()
    if already_sent:
        log.status = 'sent'
        log.error_message = 'Superseded: A subsequent notification was successfully delivered.'
        log.save(update_fields=['status', 'error_message'])
        messages.info(request, f"A notification for this assessment has already been delivered to {log.recipient_email}. Status marked resolved.")
        return redirect('notification_list')

    candidate = log.candidate
    test = log.test

    if not candidate.is_active:
        messages.error(request, f"Cannot retry: Candidate '{candidate.name}' ({candidate.email}) is currently deactivated.")
        return redirect('notification_list')

    if test.is_cancelled and log.notification_type != 'cancelled':
        messages.error(request, f"Cannot retry: Assessment '{test.test_name}' has been cancelled.")
        return redirect('notification_list')

    # Attempt re-dispatch
    try:
        if log.notification_type == 'registered':
            success, msg = send_registration_notification(candidate, test, request=request)
        elif log.notification_type == 'available':
            s_cnt, f_cnt = send_assessment_available_notifications(test, request=request)
            success = s_cnt > 0 or f_cnt == 0
            msg = "Dispatched" if success else "Failed to deliver"
        elif log.notification_type == 'cancelled':
            s_cnt, f_cnt = send_assessment_cancelled_notifications(test, request=request)
            success = s_cnt > 0 or f_cnt == 0
            msg = "Dispatched" if success else "Failed to deliver"
        else:
            from assessments.notifications import _format_datetime
            from django.core.mail import send_mail
            from django.conf import settings
            from django.template.loader import render_to_string

            start_str = _format_datetime(test.start_time)
            end_str = _format_datetime(test.end_time)
            notif_context = {
                'candidate_name': candidate.name,
                'notification_title': log.subject,
                'lead_message': f"Update regarding your registered assessment '{test.test_name}'.",
                'test_name': test.test_name,
                'description': test.description,
                'duration_minutes': test.duration_minutes,
                'total_questions': test.total_questions,
                'passing_marks': test.passing_marks,
                'status_display': test.status_display,
                'start_time_str': start_str,
                'end_time_str': end_str,
                'notice_title': 'Assessment Notification',
                'notice_text': 'Please check your schedule and details before starting.',
                'notice_type': 'info',
                'cta_text': 'Go to Candidate Portal',
                'cta_url': request.build_absolute_uri('/candidate/login/'),
            }
            html_message = render_to_string('emails/assessment_notification.html', notif_context)
            send_mail(
                subject=log.subject,
                message=f"Assessment notice for {test.test_name}.\n\nLog in to the Candidate Portal to take your test.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[candidate.email],
                fail_silently=False,
                html_message=html_message,
            )
            success = True
            msg = "Sent successfully."

        if success:
            log.status = 'sent'
            log.error_message = ''
            log.sent_at = timezone.now()
            log.save(update_fields=['status', 'error_message', 'sent_at'])

            ActivityLog.objects.create(
                admin=request.admin_user,
                candidate=candidate,
                activity_type='notification_retried',
                activity_details=f"Retried {log.notification_type} notification for {log.recipient_email} on test '{test.test_name}': Success."
            )
            messages.success(request, f"Notification to {log.recipient_email} retried and delivered successfully.")
        else:
            safe_err = re.sub(r'(password|secret|key|token)[=:\s]+[^\s,;]+', r'\1: [REDACTED]', str(msg), flags=re.IGNORECASE)
            log.error_message = safe_err
            log.sent_at = timezone.now()
            log.save(update_fields=['error_message', 'sent_at'])

            ActivityLog.objects.create(
                admin=request.admin_user,
                candidate=candidate,
                activity_type='notification_retried',
                activity_details=f"Retried {log.notification_type} notification for {log.recipient_email} on test '{test.test_name}': Failed ({safe_err[:100]})."
            )
            messages.error(request, f"Retry attempt failed: {safe_err}")

    except Exception as exc:
        safe_err = re.sub(r'(password|secret|key|token)[=:\s]+[^\s,;]+', r'\1: [REDACTED]', str(exc), flags=re.IGNORECASE)
        log.error_message = safe_err
        log.sent_at = timezone.now()
        log.save(update_fields=['error_message', 'sent_at'])

        ActivityLog.objects.create(
            admin=request.admin_user,
            candidate=candidate,
            activity_type='notification_retried',
            activity_details=f"Retried {log.notification_type} notification for {log.recipient_email} on test '{test.test_name}': Failed ({safe_err[:100]})."
        )
        messages.error(request, f"Retry attempt failed: {safe_err}")

    return redirect('notification_list')

