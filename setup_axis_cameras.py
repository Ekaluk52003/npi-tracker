#!/usr/bin/env python
"""
Create 3 Axis Communication Camera projects with ETB, Pre-series, FAA stages.
Run with: python setup_axis_cameras.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from datetime import date, timedelta
from django.contrib.auth import get_user_model
from core.models import Project, Milestone, BuildStage, Task, TeamMember

User = get_user_model()

print("=" * 60)
print("CREATE 3 AXIS CAMERA PROJECTS")
print("=" * 60)

# Clear database
print("\n1. Clearing existing data...")
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DELETE FROM core_taskduedatechange;")
    cursor.execute("DELETE FROM core_projectplanversion;")
    cursor.execute("DELETE FROM core_task_depends_on;")
    cursor.execute("DELETE FROM core_task;")
    cursor.execute("DELETE FROM core_issue;")
    cursor.execute("DELETE FROM core_milestone;")
    cursor.execute("DELETE FROM core_buildstage;")
    cursor.execute("DELETE FROM core_project;")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name LIKE 'core_%';")
    cursor.execute("PRAGMA foreign_keys = ON;")
print("   Data cleared.")

admin_user = User.objects.filter(is_staff=True).first()
if not admin_user:
    admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')

# Create test users with different roles
print("\n2. Creating test users...")
test_users = {
    'engineer': User.objects.create_user('engineer', 'engineer@example.com', 'pass123', first_name='John', last_name='Engineer'),
    'quality': User.objects.create_user('quality', 'quality@example.com', 'pass123', first_name='Sarah', last_name='Quality'),
    'pm': User.objects.create_user('pm', 'pm@example.com', 'pass123', first_name='Mike', last_name='PM'),
}
print(f"   Created: engineer, quality, pm (password: pass123)")

def create_camera_project(name, product_code, color, start_day_offset=0, users=None):
    """Create a camera project with ETB, Pre-series, FAA stages."""
    base_date = date.today() + timedelta(days=start_day_offset)

    project = Project.objects.create(
        name=name,
        product_code=product_code,
        start_date=base_date,
        end_date=base_date + timedelta(days=90),
        color=color,
        pgm=admin_user
    )

    # Add team members with roles
    if users:
        TeamMember.objects.create(
            project=project, user=users['engineer'], member_type='internal',
            role='Engineer', name='John Engineer'
        )
        TeamMember.objects.create(
            project=project, user=users['quality'], member_type='internal',
            role='Quality Manager', name='Sarah Quality'
        )
        TeamMember.objects.create(
            project=project, user=users['pm'], member_type='internal',
            role='Program Manager', name='Mike PM'
        )
        TeamMember.objects.create(
            project=project, user=admin_user, member_type='internal',
            role='Admin', name='Admin User'
        )

    # 3 Milestones per project
    milestones = {
        'Planning': Milestone.objects.create(project=project, name='Planning', sort_order=0),
        'Material': Milestone.objects.create(project=project, name='Material', sort_order=1),
        'Build': Milestone.objects.create(project=project, name='Build', sort_order=2),
        'Approval': Milestone.objects.create(project=project, name='Approval', sort_order=3),
    }
    
    # 3 Build Stages: ETB, Pre-series, FAA
    stages = {
        'ETB': BuildStage.objects.create(project=project, name='ETB', color='#3B82F6', sort_order=0),
        'PreSeries': BuildStage.objects.create(project=project, name='Pre-series', color='#8B5CF6', sort_order=1),
        'FAA': BuildStage.objects.create(project=project, name='FAA', color='#10B981', sort_order=2),
    }
    
    return project, milestones, stages, base_date

def create_tasks_for_project(project, milestones, stages, base_date, users=None):
    """Create all tasks for a camera project."""
    task_count = 0

    # User assignment rotation for variety
    assignees = [users['engineer'], users['quality'], users['pm'], admin_user] if users else [None]
    assignee_idx = 0
    def get_next_assignee():
        nonlocal assignee_idx
        user = assignees[assignee_idx % len(assignees)]
        assignee_idx += 1
        return user
    
    # === ETB STAGE ===
    print(f"    Creating ETB tasks...")
    
    # Team Setup (ETB)
    team_setup = Task.objects.create(
        project=project,
        name='Team Setup',
        milestone=milestones['Planning'],
        stage=stages['ETB'],
        start=base_date,
        end=base_date + timedelta(days=7),
        status='open',
        is_summary=True,
        sort_order=0
    )
    
    team_tasks = [
        'Form team',
        'Kickoff meeting',
        'Review demand',
        'Capacity check',
    ]
    for i, name in enumerate(team_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Planning'],
            stage=stages['ETB'], parent=team_setup,
            start=base_date + timedelta(days=i),
            end=base_date + timedelta(days=i+3),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # Material (ETB)
    material = Task.objects.create(
        project=project,
        name='Material ETB',
        milestone=milestones['Material'],
        stage=stages['ETB'],
        start=base_date + timedelta(days=5),
        end=base_date + timedelta(days=25),
        status='open',
        is_summary=True,
        sort_order=1
    )
    
    material_tasks = [
        'Auth components',
        'New supplier setup',
        'Secure material',
        'Review PPV',
        'Check freight cost',
    ]
    for i, name in enumerate(material_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Material'],
            stage=stages['ETB'], parent=material,
            start=base_date + timedelta(days=5+i*4),
            end=base_date + timedelta(days=10+i*4),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # PCBA (ETB)
    pcba_etb = Task.objects.create(
        project=project,
        name='PCBA ETB',
        milestone=milestones['Build'],
        stage=stages['ETB'],
        start=base_date + timedelta(days=20),
        end=base_date + timedelta(days=50),
        status='open',
        is_summary=True,
        sort_order=2
    )
    
    pcba_etb_tasks = [
        'PCB RFQ',
        'Issue PO PCB',
        'EQ approval',
        'Follow WG',
        'Order stencil',
        'SMT plan',
        'Release PO',
        'Start SMT',
        'Ship DHL',
    ]
    for i, name in enumerate(pcba_etb_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Build'],
            stage=stages['ETB'], parent=pcba_etb,
            start=base_date + timedelta(days=20+i*3),
            end=base_date + timedelta(days=25+i*3),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # Boxbuild (ETB)
    box_etb = Task.objects.create(
        project=project,
        name='Boxbuild ETB',
        milestone=milestones['Build'],
        stage=stages['ETB'],
        start=base_date + timedelta(days=45),
        end=base_date + timedelta(days=65),
        status='open',
        is_summary=True,
        sort_order=3
    )
    
    box_etb_tasks = [
        'Mech RFQ',
        'PO mech',
        'Design fixture',
        'Order fixture',
        'Release build',
        'Start build',
    ]
    for i, name in enumerate(box_etb_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Build'],
            stage=stages['ETB'], parent=box_etb,
            start=base_date + timedelta(days=45+i*3),
            end=base_date + timedelta(days=50+i*3),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # === PRE-SERIES STAGE ===
    print(f"    Creating Pre-series tasks...")
    
    # Material (Pre-series)
    material_ps = Task.objects.create(
        project=project,
        name='Material Pre-series',
        milestone=milestones['Material'],
        stage=stages['PreSeries'],
        start=base_date + timedelta(days=50),
        end=base_date + timedelta(days=70),
        status='open',
        is_summary=True,
        sort_order=4
    )
    
    material_ps_tasks = [
        'Check stock',
        'Order shortage',
        'Confirm delivery',
    ]
    for i, name in enumerate(material_ps_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Material'],
            stage=stages['PreSeries'], parent=material_ps,
            start=base_date + timedelta(days=50+i*6),
            end=base_date + timedelta(days=56+i*6),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # PCBA (Pre-series)
    pcba_ps = Task.objects.create(
        project=project,
        name='PCBA Pre-series',
        milestone=milestones['Build'],
        stage=stages['PreSeries'],
        start=base_date + timedelta(days=65),
        end=base_date + timedelta(days=80),
        status='open',
        is_summary=True,
        sort_order=5
    )
    
    pcba_ps_tasks = [
        'Plan SMT PS',
        'Kit material',
        'Run SMT PS',
        'AOI check',
        'Release PCB',
    ]
    for i, name in enumerate(pcba_ps_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Build'],
            stage=stages['PreSeries'], parent=pcba_ps,
            start=base_date + timedelta(days=65+i*3),
            end=base_date + timedelta(days=70+i*3),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # Boxbuild (Pre-series)
    box_ps = Task.objects.create(
        project=project,
        name='Boxbuild Pre-series',
        milestone=milestones['Build'],
        stage=stages['PreSeries'],
        start=base_date + timedelta(days=75),
        end=base_date + timedelta(days=85),
        status='open',
        is_summary=True,
        sort_order=6
    )
    
    box_ps_tasks = [
        'Kit mech parts',
        'Run build PS',
        'Test units',
        'Pack PS',
    ]
    for i, name in enumerate(box_ps_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Build'],
            stage=stages['PreSeries'], parent=box_ps,
            start=base_date + timedelta(days=75+i*2),
            end=base_date + timedelta(days=78+i*2),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # === FAA STAGE ===
    print(f"    Creating FAA tasks...")
    
    # Evaluation
    eval_faa = Task.objects.create(
        project=project,
        name='FAA Eval',
        milestone=milestones['Approval'],
        stage=stages['FAA'],
        start=base_date + timedelta(days=80),
        end=base_date + timedelta(days=95),
        status='open',
        is_summary=True,
        sort_order=7
    )
    
    eval_tasks = [
        'Build eval',
        'Test report',
        'Customer review',
        'FAA sign-off',
    ]
    for i, name in enumerate(eval_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Approval'],
            stage=stages['FAA'], parent=eval_faa,
            start=base_date + timedelta(days=80+i*4),
            end=base_date + timedelta(days=85+i*4),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    # Internal Actions
    internal = Task.objects.create(
        project=project,
        name='Internal Actions',
        milestone=milestones['Approval'],
        stage=stages['FAA'],
        start=base_date + timedelta(days=85),
        end=base_date + timedelta(days=100),
        status='open',
        is_summary=True,
        sort_order=8
    )
    
    internal_tasks = [
        'RCA meeting',
        'Scrap review',
        'Update STD cost',
        'Load SO SAP',
        'Update quote',
    ]
    for i, name in enumerate(internal_tasks):
        Task.objects.create(
            project=project, name=name, milestone=milestones['Approval'],
            stage=stages['FAA'], parent=internal,
            start=base_date + timedelta(days=85+i*3),
            end=base_date + timedelta(days=90+i*3),
            status='open', sort_order=i,
            assigned_to=get_next_assignee()
        )
        task_count += 1
    
    return task_count

# Create 3 Camera Projects
projects_data = [
    ('Fixed Dome Camera', 'FDC-001', '#3B82F6', 0),
    ('PTZ Camera', 'PTZ-002', '#8B5CF6', 30),
    ('Bullet Camera', 'BLT-003', '#10B981', 60),
]

total_tasks = 0
project_summaries = []

for name, code, color, offset in projects_data:
    print(f"\n3. Creating {name}...")
    project, milestones, stages, base_date = create_camera_project(name, code, color, offset, test_users)
    count = create_tasks_for_project(project, milestones, stages, base_date, test_users)
    total_tasks += count
    project_summaries.append((name, code, count))
    print(f"   Created {count} tasks")

# Summary
print("\n" + "=" * 60)
print("SUMMARY - 3 AXIS CAMERA PROJECTS")
print("=" * 60)

for name, code, count in project_summaries:
    print(f"\n{name} ({code})")
    print(f"  Tasks: {count}")
    print(f"  Stages: ETB | Pre-series | FAA")

print(f"\nTOTAL: {total_tasks} tasks across 3 projects")
print("\nTest Users Created:")
print("  - engineer / pass123 (Engineer role)")
print("  - quality / pass123 (Quality Manager role)")
print("  - pm / pass123 (Program Manager role)")
print("  - admin / admin123 (Admin role)")
print("\nNext steps:")
print("1. Visit http://127.0.0.1:8000/my-tasks/")
print("2. Login as any test user to see My Tasks")
print("3. View My Teammate Tasks section with role filter buttons")
print("4. Use 'By Deliverable' view to see ETB/Pre-series/FAA progress")
print("5. Use Timeline view to compare 3 projects")
print("6. Filter by role to see teammate tasks by role (Engineer, Quality, PM)")
print("=" * 60)
