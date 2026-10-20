web: gunicorn -c gunicorn.conf.py config.wsgi:application
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
