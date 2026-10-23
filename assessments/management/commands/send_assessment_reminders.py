"""
Management command to send assessment window reminders to eligible registered candidates.

Usage:
    python manage.py send_assessment_reminders [--hours 24] [--dry-run]
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from assessments.models import Test, TestRegistration
from assessments.notifications import send_assessment_reminder_notification
from attempts.models import TestAttempt


class Command(BaseCommand):
    help = "Dispatches upcoming and closing-window assessment reminders to eligible registered candidates."

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help="Horizon window in hours to look ahead for test start or closing times (default: 24)."
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate reminder scanning without dispatching emails."
        )

    def handle(self, *args, **options):
        hours = options['hours']
        dry_run = options['dry_run']
        now = timezone.now()
        horizon = now + timedelta(hours=hours)

        self.stdout.write(
            self.style.NOTICE(f"Scanning for assessment reminders within next {hours} hours (until {horizon})...")
        )

        # 1. Eligible tests: active, not cancelled, and within horizon window
        tests = Test.objects.filter(
            is_active=True,
            is_cancelled=False
        )

        target_tests = []
        for t in tests:
            # Upcoming test starting within horizon
            if t.start_time and now <= t.start_time <= horizon:
                target_tests.append((t, 'upcoming_start'))
            # In-progress test ending within horizon
            elif t.end_time and now <= t.end_time <= horizon:
                target_tests.append((t, 'closing_window'))

        if not target_tests:
            self.stdout.write(self.style.SUCCESS("No tests require reminders in the specified horizon."))
            return

        total_sent = 0
        total_skipped = 0
        total_failed = 0

        for test, reason in target_tests:
            self.stdout.write(f"Checking test '{test.test_name}' ({reason})...")

            # Get registrations with active candidates
            regs = TestRegistration.objects.filter(
                test=test,
                status='registered',
                candidate__is_active=True
            ).select_related('candidate')

            for reg in regs:
                cand = reg.candidate

                # Exclude if candidate already finalized an attempt
                has_finalized = TestAttempt.objects.filter(
                    registration=reg,
                    status__in=['completed', 'expired']
                ).exists()
                if has_finalized:
                    total_skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY RUN] Would send reminder to {cand.name} ({cand.email})")
                    total_sent += 1
                else:
                    success, msg = send_assessment_reminder_notification(cand, test)
                    if success:
                        if "already" in msg.lower():
                            total_skipped += 1
                        else:
                            total_sent += 1
                            self.stdout.write(f"  Sent reminder to {cand.name} ({cand.email})")
                    else:
                        total_failed += 1
                        self.stderr.write(f"  Failed to send reminder to {cand.name} ({cand.email}): {msg}")

        summary = (
            f"Reminder run complete: {total_sent} sent, {total_skipped} skipped/duplicate, {total_failed} failed."
        )
        if dry_run:
            summary = "[DRY RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
