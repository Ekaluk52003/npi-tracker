from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_project_product_code'),
    ]

    operations = [
        # Rename ProjectSection model → Milestone (renames DB table core_projectsection → core_milestone)
        migrations.RenameModel(
            old_name='ProjectSection',
            new_name='Milestone',
        ),
        # Rename SectionTemplate model → MilestoneTemplate (renames DB table core_sectiontemplate → core_milestonetemplate)
        migrations.RenameModel(
            old_name='SectionTemplate',
            new_name='MilestoneTemplate',
        ),
        # Rename Task.section FK field → Task.milestone (renames DB column section_id → milestone_id)
        migrations.RenameField(
            model_name='task',
            old_name='section',
            new_name='milestone',
        ),
        # Rename TaskTemplate.section FK field → TaskTemplate.milestone
        migrations.RenameField(
            model_name='tasktemplate',
            old_name='section',
            new_name='milestone',
        ),
        # Update Task ordering to use milestone__sort_order
        migrations.AlterModelOptions(
            name='task',
            options={'ordering': ['milestone__sort_order', 'start']},
        ),
        # Update related_name on Milestone.project FK: sections → milestones
        migrations.AlterField(
            model_name='milestone',
            name='project',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='milestones',
                to='core.project',
            ),
        ),
        # Update related_name on MilestoneTemplate.template_set FK: sections → milestones
        migrations.AlterField(
            model_name='milestonetemplate',
            name='template_set',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='milestones',
                to='core.tasktemplateset',
            ),
        ),
    ]
