from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_add_role_is_internal'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='category',
            field=models.CharField(
                choices=[
                    ('design', 'Design'),
                    ('quality', 'Quality'),
                    ('supplier', 'Supplier'),
                    ('process', 'Process'),
                    ('test', 'Test'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='issue',
            name='reported_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reported_issues',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='issue',
            name='resolution',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='issue',
            name='resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='issue',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='issue',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
