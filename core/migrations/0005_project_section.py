import django.db.models.deletion
from django.db import migrations, models


def migrate_sections_forward(apps, schema_editor):
    """Create ProjectSection records from existing Task.section CharField values."""
    Task = apps.get_model('core', 'Task')
    ProjectSection = apps.get_model('core', 'ProjectSection')

    # Get unique (project_id, section) pairs
    pairs = (
        Task.objects
        .values_list('project_id', 'section')
        .distinct()
        .order_by('project_id', 'section')
    )

    # Create ProjectSection for each unique pair
    section_map = {}  # (project_id, section_name) -> ProjectSection.pk
    for i, (project_id, section_name) in enumerate(pairs):
        # Group sort_order per project
        key = (project_id, section_name)
        if key not in section_map:
            ps, _ = ProjectSection.objects.get_or_create(
                project_id=project_id,
                name=section_name or 'General',
                defaults={'sort_order': i},
            )
            section_map[key] = ps.pk

    # Update tasks to point to new FK
    for (project_id, section_name), section_pk in section_map.items():
        Task.objects.filter(
            project_id=project_id,
            section=section_name,
        ).update(section_fk_id=section_pk)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_remove_tasktemplate_template_set_sectiontemplate_and_more'),
    ]

    operations = [
        # 1. Create ProjectSection model
        migrations.CreateModel(
            name='ProjectSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('sort_order', models.IntegerField(default=0)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='core.project')),
            ],
            options={
                'ordering': ['sort_order', 'id'],
                'unique_together': {('project', 'name')},
            },
        ),

        # 2. Add temporary nullable FK on Task
        migrations.AddField(
            model_name='task',
            name='section_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+',
                to='core.projectsection',
            ),
        ),

        # 3. Data migration: create sections and link tasks
        migrations.RunPython(migrate_sections_forward, migrations.RunPython.noop),

        # 4. Remove old section CharField
        migrations.RemoveField(
            model_name='task',
            name='section',
        ),

        # 5. Rename section_fk to section
        migrations.RenameField(
            model_name='task',
            old_name='section_fk',
            new_name='section',
        ),

        # 6. Make section non-nullable
        migrations.AlterField(
            model_name='task',
            name='section',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='tasks',
                to='core.projectsection',
            ),
        ),

        # 7. Update Task ordering
        migrations.AlterModelOptions(
            name='task',
            options={'ordering': ['section__sort_order', 'start']},
        ),
    ]
