"""
Management command to create an administrator account securely.

Usage:
    python manage.py create_admin --email admin@example.com --name "Admin Name" --password "SecurePass123"

Or interactively:
    python manage.py create_admin
"""
import getpass
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from accounts.models import Admin


class Command(BaseCommand):
    help = 'Create a new administrator account for HireScan.'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, help='Administrator email address')
        parser.add_argument('--name', type=str, help='Administrator full name')
        parser.add_argument('--password', type=str, help='Administrator password (will prompt if not provided)')

    def handle(self, *args, **options):
        email = options.get('email')
        name = options.get('name')
        password = options.get('password')

        # Interactive mode if arguments not provided
        if not email:
            email = input('Email: ').strip().lower()
        else:
            email = email.strip().lower()

        if not name:
            name = input('Full name: ').strip()

        if not password:
            password = getpass.getpass('Password: ')
            password_confirm = getpass.getpass('Confirm password: ')
            if password != password_confirm:
                raise CommandError('Passwords do not match.')

        # Validate email
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError(f'Invalid email address: {email}')

        # Validate name
        if not name or len(name) < 2:
            raise CommandError('Name must be at least 2 characters.')

        # Validate password strength
        if len(password) < 8:
            raise CommandError('Password must be at least 8 characters.')

        # Check for existing admin
        if Admin.objects.filter(email=email).exists():
            raise CommandError(f'An administrator with email {email} already exists.')

        # Create admin
        admin = Admin(name=name, email=email)
        admin.set_password(password)
        admin.save()

        self.stdout.write(self.style.SUCCESS(
            f'Administrator "{name}" ({email}) created successfully.'
        ))
