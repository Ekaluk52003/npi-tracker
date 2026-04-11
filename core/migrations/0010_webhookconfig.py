from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_projectplanversion'),
    ]

    operations = [
        migrations.CreateModel(
            name='WebhookConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('url', models.URLField(max_length=2000)),
                ('event', models.CharField(choices=[('issue_critical', 'Critical Issue Created'), ('issue_created', 'Any Issue Created'), ('issue_resolved', 'Issue Resolved'), ('stage_changed', 'Build Stage Status Changed'), ('task_blocked', 'Task Blocked')], max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_triggered_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('project', models.ForeignKey(blank=True, help_text='Leave blank to receive events from all projects.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='webhooks', to='core.project')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
