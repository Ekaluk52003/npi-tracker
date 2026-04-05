# Generated migration to replace depends_on_previous with depends_on ForeignKey

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_project_section'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sectiontemplate',
            name='depends_on_previous',
        ),
        migrations.AddField(
            model_name='sectiontemplate',
            name='depends_on',
            field=models.ForeignKey(
                blank=True,
                help_text='If set, this section starts after the selected section finishes.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='dependent_sections',
                to='core.sectiontemplate',
            ),
        ),
    ]
