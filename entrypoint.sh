#!/bin/sh
set -e

echo "Pre-migration: ensuring assigned_to columns exist..."
python manage.py shell -c "
from django.db import connection
with connection.cursor() as cur:
    cur.execute(\"\"\"
        DO \$\$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='core_task' AND column_name='assigned_to_id'
            ) THEN
                ALTER TABLE core_task ADD COLUMN assigned_to_id integer NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='core_issue' AND column_name='assigned_to_id'
            ) THEN
                ALTER TABLE core_issue ADD COLUMN assigned_to_id integer NULL;
            END IF;
        END \$\$;
    \"\"\")
print('Done.')
"

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

exec "$@"
