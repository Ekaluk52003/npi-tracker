from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_inbound_webhook'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # assigned_to_id already exists in core_task DB — only update state
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='task',
                    name='assigned_to',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='assigned_tasks',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        # assigned_to_id does NOT yet exist in core_issue — add normally
        migrations.AddField(
            model_name='issue',
            name='assigned_to',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_issues',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
