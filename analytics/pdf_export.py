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
