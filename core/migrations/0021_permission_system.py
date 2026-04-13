# Generated migration for new permission system

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_default_roles_and_permissions(apps, schema_editor):
    """
    Create default roles (PM, Engineer, Customer) with permissions
    matching the legacy system behavior.
    """
    Role = apps.get_model('core', 'Role')
    RolePermission = apps.get_model('core', 'RolePermission')
    UserProfile = apps.get_model('core', 'UserProfile')
    UserRoleAssignment = apps.get_model('core', 'UserRoleAssignment')
    User = apps.get_model(settings.AUTH_USER_MODEL.split('.')[0], settings.AUTH_USER_MODEL.split('.')[1])
    
    # Define roles with their legacy key mapping
    roles_data = [
        {'key': 'pm', 'name': 'Project Manager', 'is_superuser': False},
        {'key': 'engineer', 'name': 'Engineer', 'is_superuser': False},
        {'key': 'customer', 'name': 'Customer', 'is_superuser': False},
    ]
    
    # Create roles
    roles_map = {}
    for role_data in roles_data:
        role, _ = Role.objects.get_or_create(
            key=role_data['key'],
            defaults={
                'name': role_data['name'],
                'is_superuser': role_data['is_superuser'],
                'description': f'Legacy {role_data["name"]} role migrated from UserProfile.role'
            }
        )
        roles_map[role_data['key']] = role
    
    # Define permissions for each role
    # All models in the system
    all_models = [
        'project', 'buildstage', 'milestone', 'task', 'issue',
        'teammember', 'nreitem', 'gatechecklistitem', 'projectplanversion',
        'tasktemplateset', 'webhookconfig'
    ]
    
    # PM: Full access to everything
    pm_permissions = []
    for model in all_models:
        for action in ['view', 'add', 'change', 'delete']:
            pm_permissions.append((model, action))
    
    # Engineer: View all, limited edit (for issues assigned to them - handled in code)
    engineer_permissions = []
    for model in all_models:
        engineer_permissions.append((model, 'view'))
    # Engineers can also edit tasks and issues (logic in views handles assignment)
    for model in ['task', 'issue']:
        engineer_permissions.extend([(model, 'add'), (model, 'change')])
    
    # Customer: View only for project, task, issue
    customer_permissions = [
        ('project', 'view'),
        ('task', 'view'),
        ('issue', 'view'),
    ]
    
    # Create permissions
    permissions_map = {
        'pm': pm_permissions,
        'engineer': engineer_permissions,
        'customer': customer_permissions,
    }
    
    for role_key, permissions in permissions_map.items():
        role = roles_map[role_key]
        for model_name, action in permissions:
            RolePermission.objects.get_or_create(
                role=role,
                model_name=model_name,
                action=action
            )
    
    # Migrate existing UserProfile roles to UserRoleAssignments
    # Note: Use _role directly - historical models don't have the property
    Customer = apps.get_model('core', 'Customer')
    for profile in UserProfile.objects.all():
        legacy_role = profile._role  # Use the actual field, not the property
        if legacy_role in roles_map:
            role = roles_map[legacy_role]
            # Migrate customer field if present and valid
            customer = None
            try:
                if profile.customer_id:
                    customer = Customer.objects.filter(id=profile.customer_id).first()
            except Exception:
                customer = None
            # Create global role assignment with customer
            UserRoleAssignment.objects.get_or_create(
                user=profile.user,
                role=role,
                project=None,
                defaults={'customer': customer}
            )


def reverse_migration(apps, schema_editor):
    """Reverse the migration - clean up created data."""
    Role = apps.get_model('core', 'Role')
    UserRoleAssignment = apps.get_model('core', 'UserRoleAssignment')
    
    # Delete role assignments created by this migration
    UserRoleAssignment.objects.filter(project__isnull=True).delete()
    
    # Delete roles with legacy keys
    Role.objects.filter(key__in=['pm', 'engineer', 'customer']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0020_rename_projectsection_to_milestone'),
        ('core', '0015_customer_and_userprofile'),  # Ensure UserProfile exists
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create Role model
        migrations.CreateModel(
            name='Role',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('key', models.SlugField(help_text='Unique identifier used in code', max_length=50, unique=True)),
                ('description', models.TextField(blank=True)),
                ('is_superuser', models.BooleanField(default=False, help_text='Bypass all permission checks')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        
        # Create RolePermission model
        migrations.CreateModel(
            name='RolePermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(max_length=50, choices=[
                    ('project', 'Project'),
                    ('buildstage', 'Build Stage'),
                    ('milestone', 'Milestone'),
                    ('task', 'Task'),
                    ('issue', 'Issue'),
                    ('teammember', 'Team Member'),
                    ('nreitem', 'NRE Item'),
                    ('gatechecklistitem', 'Gate Checklist Item'),
                    ('projectplanversion', 'Project Plan Version'),
                    ('tasktemplateset', 'Task Template Set'),
                    ('webhookconfig', 'Webhook Config'),
                ])),
                ('action', models.CharField(max_length=10, choices=[
                    ('view', 'View'),
                    ('add', 'Create'),
                    ('change', 'Edit'),
                    ('delete', 'Delete'),
                ])),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permissions', to='core.role')),
            ],
            options={
                'ordering': ['role', 'model_name', 'action'],
            },
        ),
        
        # Create UserRoleAssignment model
        migrations.CreateModel(
            name='UserRoleAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('project', models.ForeignKey(blank=True, help_text='Null = global role, applies to all projects', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='user_roles', to='core.project')),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_assignments', to='core.role')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_assignments', to=settings.AUTH_USER_MODEL)),
                ('customer', models.ForeignKey(blank=True, help_text='For customer-scoped access', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='user_roles', to='core.customer')),
            ],
            options={
                'ordering': ['user', '-project__isnull', 'role_id'],
            },
        ),
        
        # Add unique constraints
        migrations.AddConstraint(
            model_name='rolepermission',
            constraint=models.UniqueConstraint(fields=('role', 'model_name', 'action'), name='unique_role_model_action'),
        ),
        migrations.AddConstraint(
            model_name='userroleassignment',
            constraint=models.UniqueConstraint(fields=('user', 'role', 'project'), name='unique_user_role_project'),
        ),
        
        # Run data migration
        migrations.RunPython(create_default_roles_and_permissions, reverse_migration),
    ]
