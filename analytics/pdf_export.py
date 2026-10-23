"""
Candidate Scorecard PDF Generation Service.
Uses ReportLab to build high-fidelity, printable assessment scorecards.
"""
import io
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from attempts.services import get_topic_performance


def generate_candidate_scorecard_pdf(attempt):
    """
    Generate an official, publication-quality PDF scorecard for an evaluated TestAttempt.
    Returns bytes of the generated PDF file.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
        title=f"HireScan Scorecard - {attempt.registration.candidate.name}",
        author="HireScan Test Management Tool"
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    brand_style = ParagraphStyle(
        'HireScanBrand',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1e40af')
    )

    title_style = ParagraphStyle(
        'ScorecardTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#0f172a')
    )

    meta_label = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569')
    )

    meta_val = ParagraphStyle(
        'MetaVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0f172a')
    )

    banner_pass = ParagraphStyle(
        'BannerPass',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        alignment=1,
        textColor=colors.HexColor('#065f46')
    )

    banner_fail = ParagraphStyle(
        'BannerFail',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        alignment=1,
        textColor=colors.HexColor('#991b1b')
    )

    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1e293b')
    )

    body_style = ParagraphStyle(
        'BodySmall',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#334155')
    )

    table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#1e293b')
    )

    story = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("HireScan", brand_style),
            Paragraph("OFFICIAL ASSESSMENT SCORECARD", ParagraphStyle(
                'HeaderRight', parent=styles['Normal'], fontName='Helvetica-Bold',
                fontSize=9, leading=12, alignment=2, textColor=colors.HexColor('#64748b')
            ))
        ]
    ]
    header_table = Table(header_data, colWidths=[200, 332])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563eb'), spaceAfter=14))

    # 2. Candidate & Test Details Table
    candidate = attempt.registration.candidate
    test = attempt.registration.test

    details_data = [
        [
            Paragraph("Candidate Name:", meta_label),
            Paragraph(candidate.name, meta_val),
            Paragraph("Assessment:", meta_label),
            Paragraph(test.test_name, meta_val),
        ],
        [
            Paragraph("Candidate Email:", meta_label),
            Paragraph(candidate.email, meta_val),
            Paragraph("Duration Limit:", meta_label),
            Paragraph(f"{test.duration_minutes} minutes", meta_val),
        ],
        [
            Paragraph("Completed On:", meta_label),
            Paragraph(attempt.end_time.strftime("%Y-%m-%d %H:%M UTC") if attempt.end_time else "Active", meta_val),
            Paragraph("Submission Mode:", meta_label),
            Paragraph(attempt.submission_reason.title() if attempt.submission_reason else "Manual", meta_val),
        ],
        [
            Paragraph("Attempt ID:", meta_label),
            Paragraph(str(attempt.attempt_id)[:18] + "...", meta_val),
            Paragraph("Passing Marks:", meta_label),
            Paragraph(f"{test.passing_marks} / {test.total_questions}", meta_val),
        ]
    ]
    details_table = Table(details_data, colWidths=[90, 176, 95, 171])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 12))

    # 3. Pass / Fail Result Banner
    if attempt.is_passed:
        banner_text = f"PASSED &bull; Score: {attempt.score} / {attempt.total_questions} ({attempt.percentage}%)"
        banner_bg = colors.HexColor('#d1fae5')
        banner_border = colors.HexColor('#10b981')
        b_style = banner_pass
    else:
        banner_text = f"DID NOT MEET CRITERIA &bull; Score: {attempt.score or 0} / {attempt.total_questions} ({attempt.percentage or '0.00'}%)"
        banner_bg = colors.HexColor('#fee2e2')
        banner_border = colors.HexColor('#ef4444')
        b_style = banner_fail

    banner_data = [[Paragraph(banner_text, b_style)]]
    banner_table = Table(banner_data, colWidths=[532])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), banner_bg),
        ('BOX', (0, 0), (-1, -1), 1.5, banner_border),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 12))

    # 4. Metric Summary Cards
    seconds = attempt.time_taken_seconds or 0
    mins = seconds // 60
    secs = seconds % 60
    time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    metrics_data = [
        [
            Paragraph("Total Score", meta_label),
            Paragraph("Percentage", meta_label),
            Paragraph("Correct", meta_label),
            Paragraph("Incorrect", meta_label),
            Paragraph("Unanswered", meta_label),
            Paragraph("Time Taken", meta_label),
        ],
        [
            Paragraph(f"<font size=12><b>{attempt.score or 0}</b></font> / {attempt.total_questions}", meta_val),
            Paragraph(f"<font size=12><b>{attempt.percentage or '0.00'}%</b></font>", meta_val),
            Paragraph(f"<font size=12 color='#059669'><b>{attempt.correct_answers}</b></font>", meta_val),
            Paragraph(f"<font size=12 color='#dc2626'><b>{attempt.incorrect_answers}</b></font>", meta_val),
            Paragraph(f"<font size=12 color='#64748b'><b>{attempt.unanswered}</b></font>", meta_val),
            Paragraph(f"<font size=11><b>{time_str}</b></font>", meta_val),
        ]
    ]
    col_w = 532 / 6
    metrics_table = Table(metrics_data, colWidths=[col_w] * 6)
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ffffff')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 14))

    # 5. Topic-Wise Performance Breakdown
    story.append(Paragraph("Topic-Wise Competency Breakdown", section_heading))
    story.append(Spacer(1, 4))

    topic_perf = get_topic_performance(attempt)
    topic_rows = [
        [
            Paragraph("Topic / Domain", table_header),
            Paragraph("Total", table_header),
            Paragraph("Correct", table_header),
            Paragraph("Incorrect", table_header),
            Paragraph("Unanswered", table_header),
            Paragraph("Accuracy", table_header),
            Paragraph("Proficiency", table_header),
        ]
    ]

    for t in topic_perf:
        topic_rows.append([
            Paragraph(t['topic'], body_style),
            Paragraph(str(t['total']), body_style),
            Paragraph(str(t['correct']), body_style),
            Paragraph(str(t['incorrect']), body_style),
            Paragraph(str(t['unanswered']), body_style),
            Paragraph(f"{t['accuracy']}%", body_style),
            Paragraph(t['level'], body_style),
        ])

    topic_table = Table(topic_rows, colWidths=[160, 52, 55, 60, 65, 65, 75])
    topic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(topic_table)
    story.append(Spacer(1, 14))

    # 6. Recommendations & Improvement Areas
    story.append(Paragraph("Curated Technical Focus & Recommendations", section_heading))
    story.append(Spacer(1, 4))

    suggestions_list = []
    for t in topic_perf:
        for s in t.get('suggestions', []):
            if s and s not in suggestions_list:
                suggestions_list.append(f"&bull; <b>{t['topic']}</b>: {s}")

    if suggestions_list:
        rec_data = [[Paragraph(s, body_style)] for s in suggestions_list[:4]]
    else:
        rec_data = [[Paragraph("&bull; Strong understanding demonstrated across all tested competencies.", body_style)]]

    rec_table = Table(rec_data, colWidths=[532])
    rec_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(rec_table)
    story.append(Spacer(1, 16))

    # 7. Verification & Anti-tampering Footer
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor('#cbd5e1'), spaceAfter=8))
    footer_text = (
        f"This document is an authoritative examinee scorecard generated by HireScan on "
        f"{timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}. Results were computed exclusively by the server evaluation "
        f"engine. Answer keys remain confidential to protect assessment integrity."
    )
    story.append(Paragraph(footer_text, ParagraphStyle(
        'FooterText', parent=styles['Normal'], fontName='Helvetica-Oblique',
        fontSize=7, leading=10, textColor=colors.HexColor('#94a3b8'), alignment=1
    )))

    # Build PDF document
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_assessment_summary_pdf(test_id):
    """
    Generate an authoritative executive summary report in PDF for a specific test.
    Includes cohort KPIs, pass/fail metrics, statistical distribution, score brackets,
    and topic competency breakdown with the required two-line authenticated footer.
    """
    from assessments.models import Test
    from analytics.services import get_test_summary_analytics

    test = Test.objects.filter(test_id=test_id).first()
    if not test:
        raise ValueError(f"Assessment test with ID {test_id} not found.")

    summary = get_test_summary_analytics(test_id=test_id)
    if not summary:
        raise ValueError(f"Unable to compute analytics for test {test_id}.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
        title=f"HireScan Assessment Summary - {test.test_name}",
        author="HireScan Test Management Tool"
    )

    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        'HireScanBrand', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1e40af')
    )
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=colors.HexColor('#0f172a')
    )
    meta_label = ParagraphStyle(
        'MetaLabel', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#475569')
    )
    meta_val = ParagraphStyle(
        'MetaVal', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#0f172a')
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=10, leading=14, textColor=colors.HexColor('#1e293b')
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#334155')
    )
    body_bold = ParagraphStyle(
        'BodyBold', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#0f172a')
    )
    tbl_hdr = ParagraphStyle(
        'TblHdr', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#0f172a'), alignment=1
    )
    footer_line1 = ParagraphStyle(
        'Footer1', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#64748b'), alignment=1
    )
    footer_line2 = ParagraphStyle(
        'Footer2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#475569'), alignment=1
    )

    story = []

    # 1. Header
    story.append(Paragraph("HireScan", brand_style))
    story.append(Paragraph("Official Assessment Summary &amp; Cohort Performance Report", title_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1e40af'), spaceAfter=10))

    # 2. Test Configuration Meta
    start_str = timezone.localtime(test.start_time).strftime('%B %d, %Y %I:%M %p') if test.start_time else "Open Schedule"
    end_str = timezone.localtime(test.end_time).strftime('%B %d, %Y %I:%M %p') if test.end_time else "No Deadline"

    meta_rows = [
        [
            Paragraph("Assessment Title:", meta_label),
            Paragraph(test.test_name, meta_val),
            Paragraph("Generated Date:", meta_label),
            Paragraph(timezone.now().strftime('%Y-%m-%d %H:%M UTC'), meta_val),
        ],
        [
            Paragraph("Configured Duration:", meta_label),
            Paragraph(f"{test.duration_minutes} Minutes", meta_val),
            Paragraph("Passing Score:", meta_label),
            Paragraph(f"{test.passing_marks} / {test.total_questions} Questions", meta_val),
        ],
        [
            Paragraph("Schedule Window:", meta_label),
            Paragraph(f"{start_str} &rarr; {end_str}", meta_val),
            Paragraph("Bank Sufficiency:", meta_label),
            Paragraph(f"{summary['bank_count']} Questions in Bank (Sufficient: {summary['is_sufficient']})", meta_val),
        ]
    ]
    meta_table = Table(meta_rows, colWidths=[110, 156, 110, 156])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # 3. Key Cohort Metrics
    story.append(Paragraph("Executive Cohort Performance KPIs", section_heading))
    story.append(Spacer(1, 4))

    kpi_rows = [
        [
            Paragraph("Total Registered", tbl_hdr),
            Paragraph("Started / In-Progress", tbl_hdr),
            Paragraph("Finalized Examinees", tbl_hdr),
            Paragraph("Overall Pass Rate", tbl_hdr),
            Paragraph("Average Score", tbl_hdr),
            Paragraph("Median Score", tbl_hdr),
        ],
        [
            Paragraph(str(summary['total_registered']), tbl_hdr),
            Paragraph(f"{summary['started']} ({summary['in_progress']} active)", tbl_hdr),
            Paragraph(f"{summary['finalized_count']} ({summary['completed']} manual / {summary['expired']} timeout)", tbl_hdr),
            Paragraph(f"{summary['pass_rate']}%", tbl_hdr),
            Paragraph(f"{summary['avg_score']} ({summary['avg_percentage']}%)", tbl_hdr),
            Paragraph(str(summary['median_score']), tbl_hdr),
        ]
    ]
    kpi_table = Table(kpi_rows, colWidths=[80, 95, 107, 85, 85, 80])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # 4. Score Distribution Breakdown Table
    story.append(Paragraph("Score Distribution &amp; Cohort Segmentation", section_heading))
    story.append(Spacer(1, 4))

    dist_rows = [
        [
            Paragraph("Performance Bracket", tbl_hdr),
            Paragraph("Candidate Count", tbl_hdr),
            Paragraph("Proportion of Finalized Cohort (%)", tbl_hdr),
            Paragraph("Standard Score Range Reference", tbl_hdr),
        ]
    ]
    for bucket in summary.get('distribution_buckets', []):
        dist_rows.append([
            Paragraph(bucket['label'], body_bold),
            Paragraph(str(bucket['count']), tbl_hdr),
            Paragraph(f"{bucket['pct']}%", tbl_hdr),
            Paragraph(f"Min: {summary['min_score']} | Max: {summary['max_score']} | Std Dev: &plusmn;{summary['std_dev_score']}", body_style),
        ])

    dist_table = Table(dist_rows, colWidths=[150, 100, 132, 150])
    dist_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(dist_table)
    story.append(Spacer(1, 12))

    # 5. Topic Competency Summary Table
    story.append(Paragraph("Topic-Wise Accuracy &amp; Domain Performance", section_heading))
    story.append(Spacer(1, 4))

    topic_rows = [
        [
            Paragraph("Topic / Domain", tbl_hdr),
            Paragraph("Bank Questions", tbl_hdr),
            Paragraph("Appearances", tbl_hdr),
            Paragraph("Correct Answers", tbl_hdr),
            Paragraph("Accuracy Rate (%)", tbl_hdr),
            Paragraph("Proficiency Classification", tbl_hdr),
        ]
    ]
    topics = summary.get('topic_breakdown', [])
    if topics:
        for t in topics:
            topic_rows.append([
                Paragraph(t['topic'], body_bold),
                Paragraph(str(t['question_bank_count']), tbl_hdr),
                Paragraph(str(t['assigned_count']), tbl_hdr),
                Paragraph(str(t['correct_count']), tbl_hdr),
                Paragraph(f"{t['accuracy']}%", tbl_hdr),
                Paragraph(t['level'], tbl_hdr),
            ])
    else:
        topic_rows.append([
            Paragraph("No topic data recorded yet.", body_style),
            Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr),
            Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr),
        ])

    topic_table = Table(topic_rows, colWidths=[162, 70, 70, 75, 75, 80])
    topic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(topic_table)
    story.append(Spacer(1, 16))

    # 6. Verification and Mandatory 2-Line Footer
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor('#cbd5e1'), spaceAfter=8))
    story.append(Paragraph("&copy; 2026 HireScan Test Management Tool. All rights reserved.", footer_line1))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Secure Session Authentication &bull; Role-Based Access Control", footer_line2))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_candidate_results_pdf(test_id=None, filters=None):
    """
    Generate an official tabular examinee performance and results report in PDF.
    Supports filtering by test_id, candidate search, completion outcome, and date ranges.
    Includes the mandatory two-line authenticated security footer.
    """
    from attempts.models import TestAttempt
    from assessments.models import Test
    from analytics.services import parse_date_filter, calculate_candidate_rankings_and_percentiles
    from django.db.models import Q

    filters = filters or {}
    search_query = filters.get('q', '').strip()
    status_filter = filters.get('status', '').strip()
    outcome_filter = filters.get('outcome', '').strip()
    date_from = parse_date_filter(filters.get('date_from', ''))
    date_to = parse_date_filter(filters.get('date_to', ''))

    attempts_qs = TestAttempt.objects.select_related(
        'registration__test', 'registration__candidate'
    ).order_by('-start_time')

    test_obj = None
    if test_id:
        test_obj = Test.objects.filter(test_id=test_id).first()
        attempts_qs = attempts_qs.filter(registration__test_id=test_id)

    if search_query:
        attempts_qs = attempts_qs.filter(
            Q(registration__candidate__name__icontains=search_query) |
            Q(registration__candidate__email__icontains=search_query)
        )
    if status_filter:
        attempts_qs = attempts_qs.filter(status=status_filter)
    if outcome_filter == 'passed':
        attempts_qs = attempts_qs.filter(is_passed=True)
    elif outcome_filter == 'failed':
        attempts_qs = attempts_qs.filter(is_passed=False)
    if date_from:
        attempts_qs = attempts_qs.filter(start_time__date__gte=date_from)
    if date_to:
        attempts_qs = attempts_qs.filter(start_time__date__lte=date_to)

    attempts_list = list(attempts_qs[:200])  # Cap at 200 rows for memory safety

    # Precompute rankings if scoped to a single test
    rankings_map = {}
    if test_id:
        rankings_map = calculate_candidate_rankings_and_percentiles(test_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
        title="HireScan Examinee Assessment Results",
        author="HireScan Test Management Tool"
    )

    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        'HireScanBrand', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1e40af')
    )
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=colors.HexColor('#0f172a')
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#1e293b')
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor('#334155')
    )
    body_bold = ParagraphStyle(
        'BodyBold', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=colors.HexColor('#0f172a')
    )
    tbl_hdr = ParagraphStyle(
        'TblHdr', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=colors.HexColor('#0f172a'), alignment=1
    )
    footer_line1 = ParagraphStyle(
        'Footer1', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#64748b'), alignment=1
    )
    footer_line2 = ParagraphStyle(
        'Footer2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#475569'), alignment=1
    )

    story = []

    # 1. Header
    story.append(Paragraph("HireScan", brand_style))
    test_title_part = f" — {test_obj.test_name}" if test_obj else " — All Assessments"
    story.append(Paragraph(f"Official Examinee Assessment Results{test_title_part}", title_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1e40af'), spaceAfter=8))

    # 2. Meta Strip
    filter_desc = []
    if test_obj:
        filter_desc.append(f"Assessment: {test_obj.test_name}")
    if search_query:
        filter_desc.append(f"Search: '{search_query}'")
    if status_filter:
        filter_desc.append(f"Status: {status_filter.title()}")
    if outcome_filter:
        filter_desc.append(f"Outcome: {outcome_filter.title()}")
    filter_str = " | ".join(filter_desc) if filter_desc else "Active Filter: Complete Cohort"

    story.append(Paragraph(f"<b>Filter Scope:</b> {filter_str} &bull; <b>Total Records:</b> {len(attempts_list)} examinee(s)", body_style))
    story.append(Spacer(1, 8))

    # 3. Tabular Examinee Results
    res_rows = [
        [
            Paragraph("Rank", tbl_hdr),
            Paragraph("Candidate Name", tbl_hdr),
            Paragraph("Email Address", tbl_hdr),
            Paragraph("Assessment Test", tbl_hdr),
            Paragraph("Score", tbl_hdr),
            Paragraph("Pct (%)", tbl_hdr),
            Paragraph("Outcome", tbl_hdr),
            Paragraph("Completed Date", tbl_hdr),
        ]
    ]

    for idx, att in enumerate(attempts_list, start=1):
        cand = att.registration.candidate
        test = att.registration.test
        rank_data = rankings_map.get(str(att.attempt_id))
        rank_display = str(rank_data['rank']) if rank_data else str(idx)

        score_display = f"{att.score}/{att.total_questions}" if att.score is not None else "—"
        pct_display = f"{att.percentage}%" if att.percentage is not None else "—"
        outcome_display = "Passed" if att.is_passed else ("Failed" if att.is_passed is False else att.status.title())
        date_str = (att.end_time or att.start_time).strftime('%Y-%m-%d %H:%M')

        res_rows.append([
            Paragraph(rank_display, tbl_hdr),
            Paragraph(cand.name[:22], body_bold),
            Paragraph(cand.email[:25], body_style),
            Paragraph(test.test_name[:20], body_style),
            Paragraph(score_display, tbl_hdr),
            Paragraph(pct_display, tbl_hdr),
            Paragraph(outcome_display, tbl_hdr),
            Paragraph(date_str, body_style),
        ])

    if len(attempts_list) == 0:
        res_rows.append([
            Paragraph("No examinee attempt records found matching active filter criteria.", body_style),
            Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr),
            Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr), Paragraph("—", tbl_hdr),
        ])

    res_table = Table(res_rows, colWidths=[35, 95, 115, 95, 45, 45, 45, 65])
    res_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(res_table)
    story.append(Spacer(1, 14))

    # 4. Mandatory 2-Line Footer
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor('#cbd5e1'), spaceAfter=8))
    story.append(Paragraph("&copy; 2026 HireScan Test Management Tool. All rights reserved.", footer_line1))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Secure Session Authentication &bull; Role-Based Access Control", footer_line2))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
