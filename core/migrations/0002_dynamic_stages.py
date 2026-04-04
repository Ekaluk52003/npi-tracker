# Custom migration: convert hardcoded stage choices to dynamic ForeignKey stages

import django.db.models.deletion
from django.db import migrations, models


def migrate_stage_data(apps, schema_editor):
    """Convert old CharField stage values to FK references using the new stage_fk fields."""
    BuildStage = apps.get_model('core', 'BuildStage')
    Task = apps.get_model('core', 'Task')
    Issue = apps.get_model('core', 'Issue')
    NREItem = apps.get_model('core', 'NREItem')

    # Set default colors on existing BuildStage records based on stage_id
    color_map = {'etb': '#f59e0b', 'ps': '#8b5cf6', 'fas': '#06b6d4'}
    for bs in BuildStage.objects.all():
        bs.color = color_map.get(bs.stage_id, '#3b82f6')
        bs.save(update_fields=['color'])

    # For Task, Issue, NREItem: look up the BuildStage by project + old stage value
    for Model in [Task, Issue, NREItem]:
        for obj in Model.objects.exclude(stage='').exclude(stage__isnull=True):
            try:
                bs = BuildStage.objects.get(project=obj.project, stage_id=obj.stage)
                obj.stage_fk = bs
                obj.save(update_fields=['stage_fk'])
            except BuildStage.DoesNotExist:
                pass


def reverse_stage_data(apps, schema_editor):
    """Reverse: copy FK back to CharField."""
    Task = apps.get_model('core', 'Task')
    Issue = apps.get_model('core', 'Issue')
    NREItem = apps.get_model('core', 'NREItem')

    for Model in [Task, Issue, NREItem]:
        for obj in Model.objects.filter(stage_fk__isnull=False).select_related('stage_fk'):
            obj.stage = obj.stage_fk.stage_id
            obj.save(update_fields=['stage'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # Step 1: Add color field to BuildStage, expand name field
        migrations.AddField(
            model_name='buildstage',
            name='color',
            field=models.CharField(default='#3b82f6', max_length=7),
        ),
        migrations.AlterField(
            model_name='buildstage',
            name='name',
            field=models.CharField(max_length=50),
        ),

        # Step 2: Add new FK fields alongside old CharField fields
        migrations.AddField(
            model_name='task',
            name='stage_fk',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks_new', to='core.buildstage'),
        ),
        migrations.AddField(
            model_name='issue',
            name='stage_fk',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issues_new', to='core.buildstage'),
        ),
        migrations.AddField(
            model_name='nreitem',
            name='stage_fk',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nre_items_new', to='core.buildstage'),
        ),

        # Step 3: Data migration - populate FK fields from old CharField values
        migrations.RunPython(migrate_stage_data, reverse_stage_data),

        # Step 4: Remove old CharField stage fields
        migrations.RemoveField(model_name='task', name='stage'),
        migrations.RemoveField(model_name='issue', name='stage'),
        migrations.RemoveField(model_name='nreitem', name='stage'),

        # Step 5: Rename new FK fields to 'stage'
        migrations.RenameField(model_name='task', old_name='stage_fk', new_name='stage'),
        migrations.RenameField(model_name='issue', old_name='stage_fk', new_name='stage'),
        migrations.RenameField(model_name='nreitem', old_name='stage_fk', new_name='stage'),

        # Step 6: Fix related_names after rename
        migrations.AlterField(
            model_name='task',
            name='stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='core.buildstage'),
        ),
        migrations.AlterField(
            model_name='issue',
            name='stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issues', to='core.buildstage'),
        ),
        migrations.AlterField(
            model_name='nreitem',
            name='stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nre_items', to='core.buildstage'),
        ),

        # Step 7: Remove old stage_id from BuildStage, update unique_together
        migrations.AlterUniqueTogether(
            name='buildstage',
            unique_together={('project', 'name')},
        ),
        migrations.RemoveField(
            model_name='buildstage',
            name='stage_id',
        ),
    ]
