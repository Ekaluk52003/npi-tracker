# Backfill: ensure assigned_to_id columns exist on core_task and core_issue.
# Migration 0014 used SeparateDatabaseAndState which only updated Django state
# but never created the actual DB column on fresh databases.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_project_product_code'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'core_task' AND column_name = 'assigned_to_id'
                    ) THEN
                        ALTER TABLE core_task ADD COLUMN assigned_to_id integer NULL
                            REFERENCES auth_user(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
                        CREATE INDEX core_task_assigned_to_id_idx ON core_task(assigned_to_id);
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'core_issue' AND column_name = 'assigned_to_id'
                    ) THEN
                        ALTER TABLE core_issue ADD COLUMN assigned_to_id integer NULL
                            REFERENCES auth_user(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
                        CREATE INDEX core_issue_assigned_to_id_idx ON core_issue(assigned_to_id);
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
