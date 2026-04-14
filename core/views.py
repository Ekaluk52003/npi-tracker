import json
import math
import threading
from collections import defaultdict, deque
from datetime import date, timedelta, datetime
from itertools import groupby
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
def forbidden_response(request, message="You don't have permission to access this resource."):
    """Return styled 403 forbidden page."""
    return render(request, '403.html', {'error_message': message}, status=403)
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction
from .models import Project, BuildStage, GateChecklistItem, Milestone, Task, Issue, TeamMember, NREItem, TaskTemplateSet, ProjectPlanVersion, WebhookConfig, InboundWebhook
from .forms import ProjectForm, TaskForm, IssueForm, TeamMemberForm, NREItemForm, BuildStageForm, GateChecklistItemForm, MilestoneForm, CommitForm
from .scheduling import generate_tasks_from_template, SchedulingError
from .permissions import (
    can_view_project, can_edit_issue, get_project_queryset,
    # New permission system
    permission_required, has_permission, can_view, can_add, can_change, can_delete,
    filter_visible_items, is_internal_user,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _htmx(request, full_tpl, partial_tpl, ctx):
    tpl = partial_tpl if request.htmx else full_tpl
    return render(request, tpl, ctx)


def _htmx_tab(request, full_tpl, partial_tpl, ctx):
    """Like _htmx but appends an OOB topbar swap for HTMX tab switches."""
    if not request.htmx:
        return render(request, full_tpl, ctx)
    content = render_to_string(partial_tpl, ctx, request=request)
    topbar = render_to_string('components/topbar.html', ctx, request=request)
    topbar_oob = topbar.replace('id="topbar"', 'id="topbar" hx-swap-oob="outerHTML"', 1)
    return HttpResponse(content + '\n' + topbar_oob)


def _project_ctx(project, tab, user=None, extra=None):
    latest_version = project.plan_versions.first()
    
    # Filter counts by visibility if user provided
    if user:
        visible_issues = filter_visible_items(project.issues.exclude(status='resolved'), user)
        open_issue_count = visible_issues.count()
    else:
        open_issue_count = project.issues.exclude(status='resolved').count()
    
    ctx = {
        'project': project,
        'active_tab': tab,
        'open_issue_count': open_issue_count,
        'nre_no_po_count': project.nre_items.filter(po_status='no-po').count(),
        'project_stages': list(project.stages.all()),
        'project_milestones': list(project.milestones.all()),
        'latest_version': latest_version,
        'has_draft': latest_version is None or project.tasks.count() != len(latest_version.task_snapshot),
    }
    if extra:
        ctx.update(extra)
    return ctx


def _fmt_money(val, symbol='฿'):
    if val is None:
        return '—'
    if val >= 1_000_000:
        return f'{symbol}{val / 1_000_000:.1f}M'
    if val >= 1_000:
        return f'{symbol}{val / 1_000:.0f}K'
    return f'{symbol}{val:,.0f}'


def _fmt_volume(val):
    if val is None:
        return '—'
    if val >= 1_000_000:
        return f'{val / 1_000_000:.1f}M'
    if val >= 1_000:
        return f'{val / 1_000:.0f}K'
    return f'{val:,}'


def _would_create_cycle(task_id, dep_id):
    """Return True if making task_id depend on dep_id would create a cycle."""
    visited = set()
    stack = [dep_id]
    while stack:
        curr = stack.pop()
        if curr == task_id:
            return True
        if curr in visited:
            continue
        visited.add(curr)
        stack.extend(Task.objects.get(pk=curr).depends_on.values_list('id', flat=True))
    return False


def _cascade_dependents(task):
    """Push direct dependents to start after task.end. Returns list of updated task dicts."""
    cascaded = []
    for dep in task.dependents.all():
        new_start = task.end + timedelta(days=1)
        if dep.start == new_start:
            continue
        dep.start = new_start
        dep.end = new_start + timedelta(days=dep.days - 1)
        dep.save()
        cascaded.append({'id': dep.id, 'start': dep.start.isoformat(), 'end': dep.end.isoformat(), 'days': dep.days})
    return cascaded


def _gantt_data_from_snapshot(version, project, user):
    stage_colors = {s.name: s.color for s in project.stages.all()}
    sections_map = {}
    
    # Filter tasks from snapshot by visibility
    is_user_internal = is_internal_user(user)
    for t in version.task_snapshot:
        visibility = t.get('visibility', 'all')
        # Skip if internal-only and user is not internal
        if visibility == 'internal' and not is_user_internal:
            continue
        sec = t.get('section', 'Uncategorised')
        sections_map.setdefault(sec, []).append(t)
    
    sections = [
        {
            'milestone': sec_name,
            'tasks': [{
                'id': t['id'],
                'name': t['name'],
                'who': t.get('who', ''),
                'assigned_to': t.get('assigned_to', ''),
                'days': t.get('days', 1),
                'start': t['start'],
                'end': t['end'],
                'status': t.get('status', 'open'),
                'stage': t.get('stage') or '',
                'stage_color': stage_colors.get(t.get('stage') or '', ''),
                'remark': (t.get('remark') or '')[:60],
                'open_issues': 0,
                'nre_count': 0,
                'depends_on': t.get('depends_on', []),
                'visibility': t.get('visibility', 'all'),
                'parent_id': t.get('parent_id'),
                'is_summary': t.get('is_summary', False),
                'progress_pct': t.get('progress_pct', 0),
                'rollup_start': t.get('rollup_start'),
                'rollup_end': t.get('rollup_end'),
            } for t in tasks],
        }
        for sec_name, tasks in sections_map.items()
    ]
    all_tasks = [t for tasks in sections_map.values() for t in tasks]
    starts = [t['start'] for t in all_tasks]
    ends = [t['end'] for t in all_tasks]
    stages_data = [{
        'stage_id': s.pk, 'name': s.name, 'color': s.color, 'status': s.status,
        'planned_date': s.planned_date.isoformat() if s.planned_date else None,
        'actual_date': s.actual_date.isoformat() if s.actual_date else None,
    } for s in project.stages.all()]
    return {
        'project_id': project.pk,
        'sections': sections,
        'stages': stages_data,
        'min_date': min(starts) if starts else date.today().isoformat(),
        'max_date': max(ends) if ends else date.today().isoformat(),
        'today': date.today().isoformat(),
        'readonly': True,
        'version_label': version.version_label,
    }


def _gantt_data_for_project(project, user, stage_filter=''):
    tasks = filter_visible_items(
        project.tasks.select_related('stage', 'milestone', 'assigned_to').prefetch_related('linked_nre', 'depends_on', 'linked_issues', 'subtasks'),
        user
    )
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        if not task_list:
            continue  # Skip sections with no visible tasks
        milestone = task_list[0].milestone
        # Also check if milestone itself is internal-only
        if milestone.visibility == 'internal' and not is_internal_user(user):
            continue  # Skip internal-only milestones for external users
        sections.append({
            'milestone': milestone.name,
            'tasks': [{
                'id': t.pk,
                'name': t.name,
                'who': t.who,
                'assigned_to': t.assigned_to.get_full_name() or t.assigned_to.username if t.assigned_to else '',
                'days': t.days,
                'start': t.start.isoformat(),
                'end': t.end.isoformat(),
                'status': t.status,
                'stage': t.stage.name if t.stage else '',
                'stage_color': t.stage.color if t.stage else '',
                'remark': t.remark[:60] if t.remark else '',
                'open_issues': t.linked_issues.exclude(status='resolved').count(),
                'nre_count': t.linked_nre.count(),
                'depends_on': list(t.depends_on.values_list('id', flat=True)),
                'visibility': t.visibility,
                'parent_id': t.parent_id,
                'is_summary': t.is_summary,
                'progress_pct': t.progress_pct,
                'rollup_start': t.rollup_start.isoformat() if t.rollup_start else t.start.isoformat(),
                'rollup_end': t.rollup_end.isoformat() if t.rollup_end else t.end.isoformat(),
            } for t in task_list],
        })
    # Use filtered tasks for date range calculation too
    all_tasks = list(tasks)
    starts = [t.start for t in all_tasks]
    ends = [t.end for t in all_tasks]
    stages_data = []
    for s in project.stages.all():
        stages_data.append({
            'stage_id': s.pk,
            'name': s.name,
            'color': s.color,
            'status': s.status,
            'planned_date': s.planned_date.isoformat() if s.planned_date else None,
            'actual_date': s.actual_date.isoformat() if s.actual_date else None,
        })
    return {
        'project_id': project.pk,
        'sections': sections,
        'stages': stages_data,
        'min_date': min(starts).isoformat() if starts else date.today().isoformat(),
        'max_date': max(ends).isoformat() if ends else date.today().isoformat(),
        'today': date.today().isoformat(),
    }


def _portfolio_gantt_data(projects):
    rows = []
    all_dates = []
    for p in projects:
        stages = []
        for s in p.stages.all():
            d = s.actual_date or s.planned_date
            if d:
                all_dates.append(d)
            stages.append({
                'stage_id': s.pk,
                'name': s.name,
                'color': s.color,
                'status': s.status,
                'date': d.isoformat() if d else None,
            })
        current = p.current_stage
        rows.append({
            'id': p.pk,
            'name': p.name,
            'color': p.color,
            'current_stage': current.pk if current else None,
            'current_stage_label': current.name if current else '—',
            'status': p.overall_status,
            'stages': stages,
        })
    if not all_dates:
        all_dates = [date.today()]
    return {
        'rows': rows,
        'min_date': (min(all_dates) - timedelta(weeks=4)).isoformat(),
        'max_date': (max(all_dates) + timedelta(weeks=8)).isoformat(),
        'today': date.today().isoformat(),
    }


# ── Portfolio ────────────────────────────────────────────────────────────

@login_required
def portfolio(request):
    # Filter projects based on user role (customers see only their projects)
    all_projects = Project.objects.prefetch_related('stages', 'tasks', 'issues', 'nre_items').all()
    projects = get_project_queryset(request.user, all_projects)
    
    # Example of programmatic permission checks (new system)
    # You can check permissions in views like this:
    # if can_add(request.user, 'project'):
    #     # Show create project button
    # if can_change(request.user, 'project', project):
    #     # Show edit button for this project
    # if has_permission(request.user, 'task', 'change', project):
    #     # Check specific permission on specific project
    project_rows = []
    for p in projects:
        cs = p.current_stage
        project_rows.append({
            'project': p,
            'status': p.overall_status,
            'status_label': p.overall_status_label,
            'current_stage': cs,
            'stages': list(p.stages.all()),
            'revenue_fmt': _fmt_money(p.annual_revenue, p.currency_symbol) if p.annual_revenue else '—',
            'volume_fmt': _fmt_volume(p.annual_volume),
            'open_issues': p.open_issue_count,
            'has_critical': p.has_critical_issue,
            'task_progress': p.task_progress,
        })
    gantt_data = _portfolio_gantt_data(projects)
    ctx = {
        'page_title': 'Portfolio',
        'project_rows': project_rows,
        'portfolio_gantt_data': gantt_data,
    }
    return _htmx(request, 'portfolio/portfolio.html', 'portfolio/_content.html', ctx)


@login_required
def project_issues_modal(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    issues = filter_visible_items(project.issues.select_related('stage'), request.user)
    return render(request, 'portfolio/_issues_modal.html', {'project': project, 'issues': issues})


# ── My Tasks ────────────────────────────────────────────────────────────

@login_required
def my_tasks(request):
    user = request.user
    today = date.today()

    # All tasks assigned to current user (not done)
    all_tasks_qs = Task.objects.filter(
        assigned_to=user,
    ).exclude(status='done').select_related(
        'project', 'milestone', 'stage', 'parent'
    ).prefetch_related(
        'depends_on', 'due_date_changes', 'linked_issues', 'subtasks'
    )

    # Calculate blocker info for each task
    tasks_with_blockers = []
    all_date_changes = []
    overdue_count = 0
    this_week_count = 0

    for task in all_tasks_qs:
        # Blocker info
        incomplete_deps = [d for d in task.depends_on.all() if d.status != 'done']
        open_issues = [i for i in task.linked_issues.all() if i.status != 'resolved']
        critical_issues = [i for i in open_issues if i.severity == 'critical']
        
        # Date changes
        unack_changes = [c for c in task.due_date_changes.all() if not c.acknowledged]
        latest_change = max(unack_changes, key=lambda c: c.detected_at) if unack_changes else None
        if latest_change:
            all_date_changes.append(latest_change)
        
        # Count stats
        if task.end < today:
            overdue_count += 1
        elif (task.end - today).days <= 7:
            this_week_count += 1

        # Status classification
        if task.status == 'blocked':
            status_category = 'blocked'
        elif task.status == 'inprogress':
            status_category = 'in_progress'
        elif task.status == 'open' and incomplete_deps:
            status_category = 'waiting'
        else:
            status_category = 'ready'

        tasks_with_blockers.append({
            'task': task,
            'status_category': status_category,
            'incomplete_deps': incomplete_deps,
            'open_issues': open_issues,
            'critical_issues': critical_issues,
            'has_blockers': bool(incomplete_deps or critical_issues),
            'date_change': latest_change,
            'days_until_due': (task.end - today).days,
        })

    # Group by deliverable (parent) for Deliverable View
    deliverables = {}
    standalone_tasks = []
    
    for task_info in tasks_with_blockers:
        task = task_info['task']
        if task.parent:
            parent_id = task.parent.id
            if parent_id not in deliverables:
                # Get parent with all its tasks
                parent = task.parent
                deliverables[parent_id] = {
                    'parent': parent,
                    'project': parent.project,
                    'stage': parent.stage,
                    'my_tasks': [],
                    'all_subtasks': list(parent.subtasks.all()),
                    'total_subtasks': parent.subtasks.count(),
                    'done_subtasks': parent.subtasks.filter(status='done').count(),
                }
            deliverables[parent_id]['my_tasks'].append(task_info)
        else:
            standalone_tasks.append(task_info)

    # Sort deliverables by project, then priority
    deliverable_list = sorted(
        deliverables.values(),
        key=lambda d: (d['project'].name, d['parent'].name)
    )

    # Timeline data (min/max dates)
    if tasks_with_blockers:
        all_dates = [t['task'].start for t in tasks_with_blockers] + [t['task'].end for t in tasks_with_blockers]
        timeline_start = min(all_dates)
        timeline_end = max(all_dates)
    else:
        timeline_start = today
        timeline_end = today + timedelta(days=30)

    # Stats for header
    stats = {
        'total': len(tasks_with_blockers),
        'overdue': overdue_count,
        'this_week': this_week_count,
        'blocked': sum(1 for t in tasks_with_blockers if t['status_category'] == 'blocked'),
        'has_date_changes': len(all_date_changes),
        'critical_issues': sum(len(t['critical_issues']) for t in tasks_with_blockers),
    }

    # Get distinct projects for filter (avoid duplicates from regroup)
    filter_projects = list({t['task'].project.id: t['task'].project for t in tasks_with_blockers}.values())
    filter_projects.sort(key=lambda p: p.name)

    # ── Teammate Tasks ─────────────────────────────────────────────────────
    # Find all projects where user is a team member
    my_project_ids = TeamMember.objects.filter(
        user=user
    ).values_list('project_id', flat=True)

    # Get all teammates (other users who are team members on the same projects)
    teammate_members = TeamMember.objects.filter(
        project_id__in=my_project_ids,
        user__isnull=False
    ).exclude(user=user).select_related('user', 'project')

    # Get unique teammate users with their role info
    teammate_user_ids = set(tm.user_id for tm in teammate_members)

    # Fetch all tasks assigned to teammates (not done)
    teammate_tasks_qs = Task.objects.filter(
        assigned_to_id__in=teammate_user_ids,
        project_id__in=my_project_ids
    ).exclude(status='done').select_related(
        'project', 'milestone', 'stage', 'parent', 'assigned_to'
    )

    # Build a map of user+project -> role for quick lookup
    user_project_role = {}
    for tm in teammate_members:
        key = (tm.user_id, tm.project_id)
        user_project_role[key] = tm.role or 'Unassigned'
        # Store user info for display
        if tm.user_id not in user_project_role:
            user_project_role[tm.user_id] = {
                'name': tm.display_name,
                'initials': tm.initials,
            }

    # Build role-based structure
    roles_map = defaultdict(lambda: {'users': set(), 'tasks': []})

    for task in teammate_tasks_qs:
        # Get role for this specific user+project combo
        role_key = (task.assigned_to_id, task.project_id)
        role = user_project_role.get(role_key, 'Unassigned')

        # Get user display info
        user_info = user_project_role.get(task.assigned_to_id, {'name': task.assigned_to.get_full_name() or task.assigned_to.username, 'initials': '??'})

        roles_map[role]['users'].add(task.assigned_to_id)

        # Add user info once per role
        if not any(u['id'] == task.assigned_to_id for u in roles_map[role].get('user_info', [])):
            if 'user_info' not in roles_map[role]:
                roles_map[role]['user_info'] = []
            roles_map[role]['user_info'].append({
                'id': task.assigned_to_id,
                'name': user_info['name'],
                'initials': user_info['initials'],
            })

        # Add task with role info attached
        task_info = {
            'task': task,
            'assignee': user_info['name'],
            'assignee_initials': user_info['initials'],
            'role': role,
        }
        if task_info not in roles_map[role]['tasks']:
            roles_map[role]['tasks'].append(task_info)

    # Group by user instead of role for collapsible sections
    users_map = defaultdict(lambda: {'tasks': [], 'role': '', 'name': '', 'initials': ''})

    for role_name, data in roles_map.items():
        for user_info in data.get('user_info', []):
            user_id = user_info['id']
            if user_id not in users_map or not users_map[user_id]['name']:
                users_map[user_id]['user_id'] = user_id
                users_map[user_id]['name'] = user_info['name']
                users_map[user_id]['initials'] = user_info['initials']
                users_map[user_id]['role'] = role_name
        for task_info in data['tasks']:
            user_id = task_info['task'].assigned_to_id
            if task_info not in users_map[user_id]['tasks']:
                users_map[user_id]['tasks'].append(task_info)

    # Convert to sorted list (by user name)
    teammate_by_user = sorted(
        [v for v in users_map.values() if v['tasks']],
        key=lambda x: x['name']
    )

    ctx = {
        'all_tasks': tasks_with_blockers,
        'deliverables': deliverable_list,
        'standalone_tasks': standalone_tasks,
        'date_changes': all_date_changes,
        'stats': stats,
        'timeline_start': timeline_start,
        'timeline_end': timeline_end,
        'today': today,
        'active_my_tasks': True,
        'filter_projects': filter_projects,
        'teammate_by_user': teammate_by_user,
    }
    return _htmx(request, 'my_tasks_page.html', 'my_tasks.html', ctx)


# ── Project Detail Tabs ──────────────────────────────────────────────────

@login_required
def project_detail(request, pk):
    return redirect('project-gantt', pk=pk)


@login_required
def project_gantt(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('stages', 'issues'), pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    version_id = request.GET.get('version', '')
    compare_version_id = request.GET.get('compare_version', '')
    viewing_version = None
    compare_version = None
    compare_data = None

    if version_id and version_id.isdigit():
        viewing_version = get_object_or_404(ProjectPlanVersion, pk=int(version_id), project=project)
        gantt_data = _gantt_data_from_snapshot(viewing_version, project, request.user)
    else:
        gantt_data = _gantt_data_for_project(project, request.user, stage_filter)

    # Handle comparison version for overlay display
    if compare_version_id and compare_version_id.isdigit():
        compare_version = get_object_or_404(ProjectPlanVersion, pk=int(compare_version_id), project=project)
        compare_data = _gantt_data_from_snapshot(compare_version, project, request.user)

    ctx = _project_ctx(project, 'gantt', request.user, {
        'gantt_data': gantt_data,
        'stage_filter': stage_filter,
        'viewing_version': viewing_version,
        'compare_version': compare_version,
        'compare_data': compare_data,
        'plan_versions': list(project.plan_versions.all()),
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_gantt.html', ctx)


@login_required
def project_list(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__milestone', 'tasks__linked_nre', 'stages', 'tasks__subtasks'), pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    if 'version' in request.GET:
        viewing_version = get_object_or_404(ProjectPlanVersion, pk=int(request.GET['version']), project=project)
        # Filter visible tasks from snapshot
        all_tasks = viewing_version.snapshot_data.get('tasks', [])
        if is_internal_user(request.user):
            tasks = [t for t in all_tasks if t.get('visibility', 'all') in ['all', 'internal']]
        else:
            tasks = [t for t in all_tasks if t.get('visibility', 'all') in ['all', 'customer']]
    else:
        tasks = filter_visible_items(
            project.tasks.select_related('milestone', 'stage').prefetch_related('linked_nre', 'depends_on', 'subtasks'),
            request.user
        )
        if stage_filter and stage_filter.isdigit():
            tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        if not task_list:
            continue
        milestone = task_list[0].milestone
        # Check if milestone itself is internal-only
        if milestone.visibility == 'internal' and not is_internal_user(request.user):
            continue

        # Build hierarchical task structure
        root_tasks = []
        children_map = {}
        for t in task_list:
            if t.parent_id:
                if t.parent_id not in children_map:
                    children_map[t.parent_id] = []
                children_map[t.parent_id].append(t)
            else:
                root_tasks.append(t)

        # Build ordered list with hierarchy info
        ordered_tasks = []
        item_num = 0
        for t in root_tasks:
            item_num += 1
            is_summary = t.is_summary or (t.id in children_map and len(children_map[t.id]) > 0)
            # Calculate progress for summary tasks
            subtasks_done = 0
            subtasks_total = 0
            if is_summary and t.id in children_map:
                subtasks_total = len(children_map[t.id])
                subtasks_done = sum(1 for c in children_map[t.id] if c.status == 'done')
            ordered_tasks.append({
                'task': t,
                'num': item_num,
                'level': 0,
                'is_summary': is_summary,
                'is_parent': t.id in children_map and len(children_map[t.id]) > 0,
                'subtasks_done_count': subtasks_done,
                'subtasks_total': subtasks_total,
            })
            # Add children
            if t.id in children_map:
                for child in children_map[t.id]:
                    item_num += 1
                    ordered_tasks.append({
                        'task': child,
                        'num': item_num,
                        'level': 1,
                        'is_summary': False,
                        'is_parent': False,
                        'parent_id': t.id,
                        'subtasks_done_count': 0,
                        'subtasks_total': 0,
                    })

        sections.append({
            'milestone': milestone.name,
            'milestone_obj': milestone,
            'tasks': ordered_tasks,
            'task_count': len(ordered_tasks),
        })
    ctx = _project_ctx(project, 'list', request.user, {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_list.html', ctx)


@login_required
def project_milestones(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('stages'), pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    tasks = filter_visible_items(
        project.tasks.select_related('stage', 'milestone'),
        request.user
    )
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        if not task_list:
            continue
        milestone = task_list[0].milestone
        # Check if milestone itself is internal-only
        if milestone.visibility == 'internal' and not is_internal_user(request.user):
            continue
        total = len(task_list)
        done = sum(1 for t in task_list if t.status == 'done')
        starts = [t.start for t in task_list]
        ends = [t.end for t in task_list]
        sections.append({
            'milestone': milestone.name,
            'milestone_obj': milestone,
            'tasks': task_list,
            'total': total,
            'done': done,
            'pct': round(done / total * 100) if total else 0,
            'start': min(starts) if starts else None,
            'end': max(ends) if ends else None,
        })
    ctx = _project_ctx(project, 'milestones', request.user, {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_milestones.html', ctx)


@login_required
def project_team(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    members = project.team_members.all()
    
    # Get visible tasks and issues once for efficiency
    visible_tasks = filter_visible_items(project.tasks.all(), request.user)
    visible_issues = filter_visible_items(project.issues.all(), request.user)
    
    for m in members:
        # For internal members, count tasks assigned to their user account
        if m.member_type == 'internal' and m.user:
            m.task_count = visible_tasks.filter(assigned_to=m.user).count()
            m.issue_count = visible_issues.filter(assigned_to=m.user).count()
        else:
            # For external members, fall back to who/owner field matching
            m.task_count = visible_tasks.filter(who__icontains=m.name).count()
            if not m.task_count and m.company:
                m.task_count = visible_tasks.filter(who__icontains=m.company).count()
            m.issue_count = visible_issues.filter(owner__icontains=m.name).count()
            if not m.issue_count and m.company:
                m.issue_count = visible_issues.filter(owner__icontains=m.company).count()
    ctx = _project_ctx(project, 'team', request.user, {'members': members})
    return _htmx_tab(request, 'project/detail.html', 'project/_team.html', ctx)


@login_required
def project_stages(request, pk):
    try:
        project = get_object_or_404(Project.objects.prefetch_related('stages__gate_items', 'tasks__stage', 'issues__stage', 'nre_items__stage'), pk=pk)
        if not can_view_project(request.user, project):
            return forbidden_response(request, "You don't have permission to view this project.")
        stages = list(project.stages.all())
        for s in stages:
            s.gate = s.gate_readiness
            s.tasks_done = s.tasks.filter(status='done').count()
            s.tasks_total = s.tasks.count()
        ctx = _project_ctx(project, 'stages', request.user, {'stages': stages})
        return _htmx_tab(request, 'project/detail.html', 'project/_stages.html', ctx)
    except Exception as e:
        import traceback
        print(f"ERROR in project_stages: {e}")
        print(traceback.format_exc())
        raise


@login_required
def project_nre(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('nre_items__stage', 'tasks', 'stages'), pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    items = project.nre_items.select_related('stage').all()
    categories = []
    for cat, group in groupby(items, key=lambda n: n.category):
        cat_items = list(group)
        categories.append({'category': cat, 'items': cat_items, 'count': len(cat_items)})
    total = sum(n.total_cost for n in items)
    covered = sum(n.total_cost for n in items if n.po_status != 'no-po')
    paid = sum(n.total_cost for n in items if n.po_status == 'paid')
    no_po = items.filter(po_status='no-po').count()
    ctx = _project_ctx(project, 'nre', request.user, {
        'categories': categories,
        'nre_total': total,
        'nre_covered': covered,
        'nre_paid': paid,
        'nre_no_po': no_po,
        'currency_symbol': project.currency_symbol,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_nre.html', ctx)


W_DIRECT = 2
W_DOWNSTREAM = 3
W_DURATION = 1


@login_required
def project_critical_index(request, pk):
    """Simplified Deliverable View: columns are parent tasks, simple progress bars."""
    project = get_object_or_404(
        Project.objects.prefetch_related(
            'tasks__stage', 'tasks__milestone', 'tasks__linked_issues', 'tasks__parent', 'stages',
        ),
        pk=pk,
    )
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")

    # Simple filters: my_work, blocked, all
    filter_mode = request.GET.get('filter', 'all')  # all, my_work, blocked

    # Get all leaf tasks (actual work units)
    task_query = project.tasks.select_related('stage', 'milestone', 'parent').filter(is_summary=False)
    if filter_mode == 'blocked':
        # Will filter after we have issue data
        pass
    tasks = list(filter_visible_items(task_query, request.user))

    # Build deliverables (parent tasks) with their subtasks
    deliverables = []
    all_issues_list = []  # All issues for the Issues column
    seen_issue_ids = set()  # Track unique issues for deduplication

    # First, separate into parented and unparented
    parented = [t for t in tasks if t.parent_id]
    unparented = [t for t in tasks if not t.parent_id]

    # Group by parent
    by_parent = defaultdict(list)
    for t in parented:
        by_parent[t.parent_id].append(t)

    # Build deliverable objects
    all_parents = {t.parent_id: t.parent for t in parented if t.parent}

    for parent_id, subtasks in by_parent.items():
        parent = all_parents.get(parent_id)
        if not parent:
            continue

        # Calculate progress
        total = len(subtasks)
        done = sum(1 for t in subtasks if t.status == 'done')
        progress_pct = round(done / total * 100) if total else 0

        # Count issues per task and collect for Issues column
        show_resolved = request.GET.get('show_resolved') == '1'
        for t in subtasks:
            all_linked = list(t.linked_issues.select_related('assigned_to', 'reported_by').all())
            visible = [i for i in all_linked if i.visibility in ('all', 'customer') or is_internal_user(request.user)]
            t._open_issues = [i for i in visible if i.status != 'resolved']
            t._resolved_issues = [i for i in visible if i.status == 'resolved']
            t.critical_count = sum(1 for i in t._open_issues if i.severity == 'critical')
            t.issue_count = len(t._open_issues)
            # Collect all visible issues (open + resolved if enabled) with task references
            issues_to_show = visible if show_resolved else t._open_issues
            for issue in issues_to_show:
                if issue.pk not in seen_issue_ids:
                    seen_issue_ids.add(issue.pk)
                    issue.linked_tasks_info = []
                    all_issues_list.append(issue)
                # Add task reference to the issue
                for existing in all_issues_list:
                    if existing.pk == issue.pk:
                        existing.linked_tasks_info.append({
                            'task_id': t.pk,
                            'task_name': t.name,
                            'deliverable_name': parent.name,
                            'deliverable_id': parent_id
                        })
                        break

        # Deliverable-level stats
        critical_issues = sum(t.critical_count for t in subtasks)

        deliverable = {
            'parent': parent,
            'subtasks': subtasks,
            'total': total,
            'done': done,
            'progress_pct': progress_pct,
            'total_issues': sum(t.issue_count for t in subtasks),
            'critical_issues': critical_issues,
            'is_blocked': critical_issues > 0,
        }
        deliverables.append(deliverable)

    # Handle unparented tasks as a pseudo-deliverable
    if unparented:
        for t in unparented:
            all_linked = list(t.linked_issues.select_related('assigned_to', 'reported_by').all())
            visible = [i for i in all_linked if i.visibility in ('all', 'customer') or is_internal_user(request.user)]
            t._open_issues = [i for i in visible if i.status != 'resolved']
            t._resolved_issues = [i for i in visible if i.status == 'resolved']
            t.critical_count = sum(1 for i in t._open_issues if i.severity == 'critical')
            t.issue_count = len(t._open_issues)
            # Collect all visible issues (open + resolved if enabled) with task references
            issues_to_show = visible if show_resolved else t._open_issues
            for issue in issues_to_show:
                if issue.pk not in seen_issue_ids:
                    seen_issue_ids.add(issue.pk)
                    issue.linked_tasks_info = []
                    all_issues_list.append(issue)
                # Add task reference to the issue
                for existing in all_issues_list:
                    if existing.pk == issue.pk:
                        existing.linked_tasks_info.append({
                            'task_id': t.pk,
                            'task_name': t.name,
                            'deliverable_name': 'Other Tasks',
                            'deliverable_id': 0
                        })
                        break

        critical_issues = sum(t.critical_count for t in unparented)

        unparented_deliverable = {
            'parent': None,
            'subtasks': unparented,
            'total': len(unparented),
            'done': sum(1 for t in unparented if t.status == 'done'),
            'progress_pct': round(sum(1 for t in unparented if t.status == 'done') / len(unparented) * 100) if unparented else 0,
            'total_issues': sum(t.issue_count for t in unparented),
            'critical_issues': critical_issues,
            'is_blocked': critical_issues > 0,
        }
        deliverables.append(unparented_deliverable)

    # Apply blocked filter
    if filter_mode == 'blocked':
        deliverables = [d for d in deliverables if d['is_blocked']]

    # Apply my_work filter
    if filter_mode == 'my_work':
        for d in deliverables:
            d['subtasks'] = [t for t in d['subtasks'] if t.assigned_to_id == request.user.pk]
        deliverables = [d for d in deliverables if d['subtasks']]

    # Sort by stage order, then by progress (ascending - struggling items first)
    stage_order = {s.name: s.sort_order for s in project.stages.all()}
    deliverables.sort(key=lambda d: (
        stage_order.get(d['parent'].stage.name if d['parent'] and d['parent'].stage else '', 999),
        -d['progress_pct'],  # Lower progress first (struggling)
        -d['critical_issues'],  # More critical issues first
    ))

    # Build deliverable groups for headers
    deliverable_groups = []
    for d in deliverables:
        name = d['parent'].name if d['parent'] else 'Other Tasks'
        color = d['parent'].stage.color if d['parent'] and d['parent'].stage else '#666'
        deliverable_groups.append({
            'name': name,
            'color': color,
            'progress_pct': d['progress_pct'],
            'is_blocked': d['is_blocked'],
        })

    today = date.today()

    ctx = _project_ctx(project, 'critical-index', request.user, {
        'deliverables': deliverables,
        'deliverable_groups_json': json.dumps(deliverable_groups),
        'all_issues': all_issues_list,
        'total_issues': len([i for i in all_issues_list if i.status != 'resolved']),
        'resolved_count': len([i for i in all_issues_list if i.status == 'resolved']),
        'today': today,
        'filter_mode': filter_mode,
        'show_resolved': show_resolved,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_critical_index.html', ctx)


# ── Project CRUD ─────────────────────────────────────────────────────────

# Example using new permission system
@permission_required('project', 'add')
def project_create(request):
    """Create a new project."""
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        print(f"POST data keys: {list(request.POST.keys())}")
        print(f"stages_json received: {request.POST.get('stages_json', 'NOT FOUND')[:200]}")
        if form.is_valid():
            project = form.save(commit=False)
            project.pm = request.user
            project.save()
            form.save_m2m()
            # Create build stages if specified
            stages_json = request.POST.get('stages_json', '').strip()
            stages_data = []
            if stages_json:
                try:
                    stages_data = json.loads(stages_json)
                    print(f"Parsed stages_data: {stages_data}")
                except json.JSONDecodeError as e:
                    print(f"Stages JSON parse error: {e}, data: {stages_json[:200]}")
                    stages_data = []
            
            # Filter out empty stages
            valid_stages = [s for s in stages_data if s.get('name', '').strip()]
            print(f"Valid stages to create: {len(valid_stages)}")
            
            if valid_stages:
                for i, stage in enumerate(valid_stages):
                    BuildStage.objects.create(
                        project=project,
                        name=stage['name'].strip(),
                        full_name=stage.get('full_name', '').strip(),
                        color=stage.get('color', '#666666'),
                        sort_order=i
                    )
            else:
                # Create default stages
                defaults = [
                    ('ETB', 'External Test Build', '#f59e0b'),
                    ('PS', 'Pre-Series Build', '#8b5cf6'),
                    ('FAS', 'First Article Sample', '#06b6d4'),
                ]
                for i, (name, full, color) in enumerate(defaults):
                    BuildStage.objects.create(
                        project=project,
                        name=name,
                        full_name=full,
                        color=color,
                        sort_order=i
                    )
            # Create default milestones
            defaults = [' EVT', 'DVT', 'PVT']
            for i, name in enumerate(defaults):
                Milestone.objects.create(
                    project=project,
                    name=name.strip(),
                    sort_order=i,
                    visibility='all'
                )
            return HttpResponse(
                f"""<script>window.location.href='{reverse('project-detail', args=[project.pk])}';</script>""",
                content_type='text/html'
            )
        else:
            return render(request, 'forms/_project_form.html', {'form': form, 'is_edit': False})
    else:
        form = ProjectForm()
    return render(request, 'forms/_project_form.html', {'form': form, 'is_edit': False})


@permission_required('project', 'change', project_param='pk')
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/stages/')})
            return redirect('project-stages', pk=pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'forms/_project_form.html', {'form': form, 'project': project, 'is_edit': True})


# ── Section CRUD ────────────────────────────────────────────────────────

@permission_required('milestone', 'add', project_param='pk')
def section_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = MilestoneForm(request.POST)
        if form.is_valid():
            milestone = form.save(commit=False)
            milestone.project = project
            if not milestone.sort_order:
                milestone.sort_order = project.milestones.count()
            milestone.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = MilestoneForm(initial={'sort_order': project.milestones.count()})
    return render(request, 'forms/_milestone_form.html', {'form': form, 'project': project})


@permission_required('milestone', 'change', project_param='pk')
def section_edit(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    milestone = get_object_or_404(Milestone, pk=sid, project=project)
    if request.method == 'POST':
        form = MilestoneForm(request.POST, instance=milestone)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = MilestoneForm(instance=milestone)
    return render(request, 'forms/_milestone_form.html', {'form': form, 'project': project, 'milestone': milestone})


@permission_required('milestone', 'delete', project_param='pk')
def section_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    milestone = get_object_or_404(Milestone, pk=sid, project=project)
    milestone.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
    return redirect('project-gantt', pk=pk)


# ── Task CRUD ────────────────────────────────────────────────────────────

@permission_required('task', 'add', project_param='pk')
def task_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = TaskForm(request.POST, project=project)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = project
            task.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'taskSaved': True, 'taskCreated': True})})
            return redirect('project-gantt', pk=pk)
    else:
        form = TaskForm(project=project, initial={'start': date.today(), 'end': date.today() + timedelta(days=7)})
    return render(request, 'forms/_task_form.html', {'form': form, 'project': project})


@permission_required('task', 'change', project_param='pk')
def task_edit(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task, project=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                task_data = {
                    'id': task.pk,
                    'name': task.name,
                    'start': task.start.isoformat(),
                    'end': task.end.isoformat(),
                    'days': task.days,
                    'status': task.status,
                    'who': task.who,
                    'assigned_to': task.assigned_to.get_full_name() or task.assigned_to.username if task.assigned_to else '',
                    'remark': task.remark[:60] if task.remark else '',
                    'stage': task.stage.name if task.stage else '',
                    'stage_color': task.stage.color if task.stage else '',
                    'open_issues': task.linked_issues.exclude(status='resolved').count(),
                    'nre_count': task.linked_nre.count(),
                }
                return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'taskSaved': True, 'taskUpdated': task_data})})
            return redirect('project-gantt', pk=pk)
    else:
        form = TaskForm(instance=task, project=project)
    return render(request, 'forms/_task_form.html', {'form': form, 'project': project, 'task': task})


@permission_required('task', 'delete', project_param='pk')
def task_delete(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    task.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'taskSaved': True, 'taskDeleted': {'id': tid}})})
    return redirect('project-gantt', pk=pk)


# ── Issue CRUD ───────────────────────────────────────────────────────────

@permission_required('issue', 'add', project_param='pk')
def issue_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    task_id = request.GET.get('task_id')
    initial = {}
    if task_id:
        try:
            task = Task.objects.get(pk=task_id, project=project)
            initial['linked_tasks'] = [task.pk]
        except Task.DoesNotExist:
            pass
    if request.method == 'POST':
        form = IssueForm(request.POST, project=project)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.project = project
            if not issue.reported_by_id:
                issue.reported_by = request.user
            issue.save()
            form.save_m2m()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/critical-index/')})
            return redirect('project-critical-index', pk=pk)
    else:
        form = IssueForm(project=project, initial=initial)
    return render(request, 'forms/_issue_form.html', {'form': form, 'project': project})


@login_required
def issue_edit(request, pk, iid):
    project = get_object_or_404(Project, pk=pk)
    issue = get_object_or_404(Issue, pk=iid, project=project)
    if not can_edit_issue(request.user, issue):
        return forbidden_response(request, "You don't have permission to edit this issue.")
    if request.method == 'POST':
        form = IssueForm(request.POST, instance=issue, project=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/critical-index/'})
            return redirect('project-critical-index', pk=pk)
    else:
        form = IssueForm(instance=issue, project=project)
    return render(request, 'forms/_issue_form.html', {'form': form, 'project': project, 'issue': issue})


# Example using new permission system
@permission_required('issue', 'delete', project_param='pk')
def issue_delete(request, pk, iid):
    project = get_object_or_404(Project, pk=pk)
    issue = get_object_or_404(Issue, pk=iid, project=project)
    issue.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/critical-index/'})
    return redirect('project-critical-index', pk=pk)


# ── Team CRUD ────────────────────────────────────────────────────────────

@permission_required('teammember', 'add', project_param='pk')
def member_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = TeamMemberForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.project = project
            member.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/team/'})
            return redirect('project-team', pk=pk)
    else:
        form = TeamMemberForm()
    return render(request, 'forms/_member_form.html', {'form': form, 'project': project})


@permission_required('teammember', 'change', project_param='pk')
def member_edit(request, pk, mid):
    project = get_object_or_404(Project, pk=pk)
    member = get_object_or_404(TeamMember, pk=mid, project=project)
    if request.method == 'POST':
        form = TeamMemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/team/'})
            return redirect('project-team', pk=pk)
    else:
        form = TeamMemberForm(instance=member)
    return render(request, 'forms/_member_form.html', {'form': form, 'project': project, 'member': member})


@permission_required('teammember', 'delete', project_param='pk')
def member_delete(request, pk, mid):
    project = get_object_or_404(Project, pk=pk)
    member = get_object_or_404(TeamMember, pk=mid, project=project)
    member.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/team/'})
    return redirect('project-team', pk=pk)


# ── NRE CRUD ─────────────────────────────────────────────────────────────

@permission_required('nreitem', 'add', project_param='pk')
def nre_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = NREItemForm(request.POST, project=project)
        if form.is_valid():
            nre = form.save(commit=False)
            nre.project = project
            nre.save()
            form.save_m2m()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/nre/'})
            return redirect('project-nre', pk=pk)
    else:
        form = NREItemForm(project=project)
    return render(request, 'forms/_nre_form.html', {'form': form, 'project': project})


@permission_required('nre', 'change', project_param='pk')
def nre_edit(request, pk, nid):
    project = get_object_or_404(Project, pk=pk)
    nre = get_object_or_404(NREItem, pk=nid, project=project)
    if request.method == 'POST':
        form = NREItemForm(request.POST, instance=nre, project=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/nre/'})
            return redirect('project-nre', pk=pk)
    else:
        form = NREItemForm(instance=nre, project=project)
    return render(request, 'forms/_nre_form.html', {'form': form, 'project': project, 'nre': nre})


@permission_required('nreitem', 'delete', project_param='pk')
def nre_delete(request, pk, nid):
    project = get_object_or_404(Project, pk=pk)
    nre = get_object_or_404(NREItem, pk=nid, project=project)
    nre.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/nre/'})
    return redirect('project-nre', pk=pk)


# ── Task Issues Modal ───────────────────────────────────────────────────

@login_required
def task_issues_modal(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    task = get_object_or_404(Task, pk=tid, project=project)
    issues = task.linked_issues.exclude(status='resolved')
    return render(request, 'forms/_task_issues_modal.html', {
        'project': project,
        'task': task,
        'issues': issues,
    })


# ── Build Stage CRUD ────────────────────────────────────────────────────

@permission_required('buildstage', 'add', project_param='pk')
def stage_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = BuildStageForm(request.POST)
        if form.is_valid():
            stage = form.save(commit=False)
            stage.project = project
            stage.sort_order = project.stages.count() + 1
            stage.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
            return redirect('project-stages', pk=pk)
    else:
        form = BuildStageForm()
    return render(request, 'forms/_stage_form.html', {
        'form': form,
        'project': project,
        'is_new': True,
    })


@permission_required('buildstage', 'change', project_param='pk')
def stage_edit(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    gate_form = GateChecklistItemForm()
    if request.method == 'POST':
        # Handle gate checklist operations first (without closing modal)
        if 'add_gate_item' in request.POST:
            gf = GateChecklistItemForm(request.POST)
            if gf.is_valid() and gf.cleaned_data.get('label'):
                item = gf.save(commit=False)
                item.stage = stage
                item.sort_order = stage.gate_items.count()
                item.save()
            gate_form = GateChecklistItemForm()
            ctx = {
                'gate_form': gate_form,
                'project': project,
                'stage': stage,
                'gate_items': stage.gate_items.all(),
                'is_new': False,
            }
            return render(request, 'forms/_gate_checklist_partial.html', ctx)
        if 'delete_gate_item' in request.POST:
            gid = request.POST.get('delete_gate_item')
            GateChecklistItem.objects.filter(pk=gid, stage=stage).delete()
            ctx = {
                'gate_form': GateChecklistItemForm(),
                'project': project,
                'stage': stage,
                'gate_items': stage.gate_items.all(),
                'is_new': False,
            }
            return render(request, 'forms/_gate_checklist_partial.html', ctx)
        if 'toggle_gate_item' in request.POST:
            gid = request.POST.get('toggle_gate_item')
            item = get_object_or_404(GateChecklistItem, pk=gid, stage=stage)
            item.checked = not item.checked
            item.save()
            ctx = {
                'gate_form': GateChecklistItemForm(),
                'project': project,
                'stage': stage,
                'gate_items': stage.gate_items.all(),
                'is_new': False,
            }
            return render(request, 'forms/_gate_checklist_partial.html', ctx)

        # Save the main stage form and redirect
        form = BuildStageForm(request.POST, instance=stage)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
            return redirect('project-stages', pk=pk)
    else:
        form = BuildStageForm(instance=stage)
    return render(request, 'forms/_stage_form.html', {
        'form': form,
        'gate_form': gate_form,
        'project': project,
        'stage': stage,
        'gate_items': stage.gate_items.all(),
    })


@permission_required('buildstage', 'delete', project_param='pk')
def stage_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    stage.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
    return redirect('project-stages', pk=pk)


@permission_required('gatechecklistitem', 'change', project_param='pk')
def gate_toggle(request, pk, sid, gid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    item = get_object_or_404(GateChecklistItem, pk=gid, stage=stage)
    item.checked = not item.checked
    item.save()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
    return redirect('project-stages', pk=pk)


# ── Apply Task Template ────────────────────────────────────────────────

@permission_required('task', 'add', project_param='pk')
def template_apply(request, pk):
    project = get_object_or_404(Project, pk=pk)
    stages = list(project.stages.order_by('sort_order'))
    template_sets = TaskTemplateSet.objects.all()
    has_existing_tasks = project.tasks.exists()

    def _render_form(error=None, selected_templates=None, stage_dates=None):
        return render(request, 'forms/_apply_template_form.html', {
            'project': project,
            'stages': stages,
            'template_sets': template_sets,
            'has_existing_tasks': has_existing_tasks,
            'error': error,
            'selected_templates_json': json.dumps(
                {str(k): str(v) for k, v in (selected_templates or {}).items()}
            ),
            'stage_dates_json': json.dumps(
                {str(k): str(v) for k, v in (stage_dates or {}).items()}
            ),
        })

    if request.method == 'POST':
        replace_existing = request.POST.get('replace_existing') == 'true'

        # Collect per-stage template + start date selections
        stage_template_pairs = []   # (stage, template_set, start_date)
        selected_templates = {}
        stage_dates = {}

        for stage in stages:
            set_pk_str = request.POST.get(f'stage_{stage.pk}_template', '')
            date_str = request.POST.get(f'stage_{stage.pk}_start_date', '')
            selected_templates[stage.pk] = set_pk_str
            stage_dates[stage.pk] = date_str

            if set_pk_str:
                try:
                    ts = TaskTemplateSet.objects.get(pk=int(set_pk_str))
                    try:
                        stage_start = date.fromisoformat(date_str) if date_str else None
                    except ValueError:
                        stage_start = None
                    stage_template_pairs.append((stage, ts, stage_start))
                except (TaskTemplateSet.DoesNotExist, ValueError):
                    pass

        if not stage_template_pairs:
            return _render_form(
                error='Please select at least one template set for a stage.',
                selected_templates=selected_templates,
                stage_dates=stage_dates,
            )

        missing = [s.name for s, ts, d in stage_template_pairs if d is None]
        if missing:
            return _render_form(
                error=f'Please set a start date for: {", ".join(missing)}',
                selected_templates=selected_templates,
                stage_dates=stage_dates,
            )

        # Parse per-milestone date overrides from POST (milestone PKs are globally unique)
        section_overrides = {}
        for key, val in request.POST.items():
            if key.startswith('milestone_date_') and val:
                try:
                    sec_pk = int(key.replace('milestone_date_', ''))
                    section_overrides[sec_pk] = date.fromisoformat(val)
                except (ValueError, TypeError):
                    pass

        try:
            all_task_dicts = []
            for stage, ts, stage_start in stage_template_pairs:
                task_dicts = generate_tasks_from_template(
                    ts, project, stage_start, section_overrides, forced_stage=stage
                )
                all_task_dicts.extend(task_dicts)

            with transaction.atomic():
                if replace_existing:
                    project.tasks.all().delete()

                milestone_cache = {}
                base_milestone_order = project.milestones.count()
                for d in all_task_dicts:
                    ms_name = d['milestone']
                    if ms_name not in milestone_cache:
                        ms, _ = Milestone.objects.get_or_create(
                            project=project, name=ms_name,
                            defaults={'sort_order': base_milestone_order + len(milestone_cache)},
                        )
                        milestone_cache[ms_name] = ms

                base_sort = project.tasks.count()
                tasks_to_create = []
                for i, d in enumerate(all_task_dicts):
                    d.pop('template_pk', None)
                    d['sort_order'] = base_sort + i
                    d['milestone'] = milestone_cache[d['milestone']]
                    tasks_to_create.append(Task(project=project, **d))
                Task.objects.bulk_create(tasks_to_create)

                # Update planned_date on each stage that was applied
                for stage, ts, stage_start in stage_template_pairs:
                    stage.planned_date = stage_start
                    stage.save(update_fields=['planned_date'])

        except SchedulingError as exc:
            return _render_form(
                error=str(exc),
                selected_templates=selected_templates,
                stage_dates=stage_dates,
            )

        if request.htmx:
            return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/gantt/'})
        return redirect('project-gantt', pk=pk)

    return _render_form()


@permission_required('tasktemplateset', 'view', project_param='pk')
def template_preview(request, pk, set_pk):
    project = get_object_or_404(Project, pk=pk)
    template_set = get_object_or_404(TaskTemplateSet, pk=set_pk)
    start_date_str = request.GET.get('start_date', '')
    try:
        preview_start = date.fromisoformat(start_date_str)
    except (ValueError, TypeError):
        preview_start = project.start_date

    # Parse per-milestone date overrides from GET
    section_overrides = {}
    for key, val in request.GET.items():
        if key.startswith('milestone_date_') and val:
            try:
                sec_pk = int(key.replace('milestone_date_', ''))
                section_overrides[sec_pk] = date.fromisoformat(val)
            except (ValueError, TypeError):
                pass

    # Generate scheduled dates for preview
    try:
        task_dicts = generate_tasks_from_template(template_set, project, preview_start, section_overrides)
    except SchedulingError:
        task_dicts = []

    pk_to_scheduled = {d['template_pk']: d for d in task_dicts}

    # Build section data with their tasks
    sections_qs = template_set.milestones.select_related('depends_on').prefetch_related('tasks__depends_on').order_by('sort_order', 'id')
    sections = []
    for sec in sections_qs:
        tasks = []
        for tmpl in sec.tasks.order_by('sort_order', 'id'):
            scheduled = pk_to_scheduled.get(tmpl.pk)
            tasks.append({
                'pk': tmpl.pk,
                'name': tmpl.name,
                'who': tmpl.who,
                'days': tmpl.days,
                'start': scheduled['start'] if scheduled else None,
                'end': scheduled['end'] if scheduled else None,
                'deps': [d.name for d in tmpl.depends_on.all()],
            })
        # Compute section date range from scheduled tasks
        task_starts = [t['start'] for t in tasks if t['start']]
        task_ends = [t['end'] for t in tasks if t['end']]
        sections.append({
            'pk': sec.pk,
            'name': sec.name,
            'depends_on': sec.depends_on.pk if sec.depends_on else None,
            'depends_on_name': sec.depends_on.name if sec.depends_on else None,
            'day_offset': sec.day_offset,
            'tasks': tasks,
            'start': min(task_starts) if task_starts else None,
            'end': max(task_ends) if task_ends else None,
        })

    has_error = len(task_dicts) == 0 and template_set.milestones.exists()

    return render(request, 'forms/_template_preview.html', {
        'project': project,
        'template_set': template_set,
        'sections': sections,
        'start_date': preview_start,
        'has_error': has_error,
    })


# ── API Endpoints ────────────────────────────────────────────────────────────

@permission_required('task', 'change')
@csrf_protect
@require_http_methods(['PATCH'])
def api_task_update(request, task_id):
    """Update task dates (start/end/sort_order/parent) via API. Cascades to direct dependents."""
    try:
        task = Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'error': 'Task not found'}, status=404)

    try:
        data = json.loads(request.body)
        updated_parent = False
        if 'start' in data:
            task.start = date.fromisoformat(data['start'])
        if 'end' in data:
            task.end = date.fromisoformat(data['end'])
        if 'sort_order' in data:
            task.sort_order = int(data['sort_order'])
        if 'parent_id' in data:
            new_parent_id = data['parent_id']
            if new_parent_id:
                # Validate: can't be own descendant, max 2 levels
                parent = Task.objects.get(pk=new_parent_id)
                if parent.pk == task.pk:
                    return JsonResponse({'error': 'Cannot set self as parent'}, status=400)
                if parent.parent_id:
                    return JsonResponse({'error': 'Maximum 2 levels of nesting'}, status=400)
                # Check if parent is a descendant of task (circular)
                if parent.parent_id == task.pk:
                    return JsonResponse({'error': 'Cannot set child as parent'}, status=400)
                task.parent = parent
            else:
                task.parent = None
            updated_parent = True
        task.save()
        # Recompute is_summary for old and new parents
        if updated_parent:
            Task.objects.filter(pk=task.parent_id).update(is_summary=True)
        cascaded = _cascade_dependents(task)
        return JsonResponse({
            'success': True,
            'start': task.start.isoformat(),
            'end': task.end.isoformat(),
            'days': task.days,
            'sort_order': task.sort_order,
            'parent_id': task.parent_id,
            'is_summary': task.is_summary,
            'cascaded': cascaded,
        })
    except (json.JSONDecodeError, ValueError, Task.DoesNotExist) as e:
        return JsonResponse({'error': f'Invalid data: {str(e)}'}, status=400)


@permission_required('task', 'change')
@csrf_protect
@require_http_methods(['POST'])
def api_task_link(request, task_id):
    """Link task_id to depend on dep_id (dep_id must finish before task_id starts)."""
    try:
        task = Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'error': 'Task not found'}, status=404)

    try:
        data = json.loads(request.body)
        dep_id = int(data['depends_on'])
        dep = Task.objects.get(pk=dep_id)
    except (json.JSONDecodeError, KeyError, ValueError, Task.DoesNotExist):
        return JsonResponse({'error': 'Invalid data'}, status=400)

    if dep_id == task.pk:
        return JsonResponse({'error': 'A task cannot depend on itself'}, status=400)

    if _would_create_cycle(task.pk, dep_id):
        return JsonResponse({'error': 'Cannot link: this would create a circular dependency'}, status=400)

    task.depends_on.add(dep)

    # Push task forward if it starts before dep ends
    cascaded = []
    if task.start <= dep.end:
        task.start = dep.end + timedelta(days=1)
        task.end = task.start + timedelta(days=task.days - 1)
        task.save()
        cascaded.append({'id': task.pk, 'start': task.start.isoformat(), 'end': task.end.isoformat(), 'days': task.days})

    return JsonResponse({'success': True, 'cascaded': cascaded})


@permission_required('task', 'change')
@csrf_protect
@require_http_methods(['POST'])
def api_task_unlink(request, task_id):
    """Remove a dependency link from task_id."""
    try:
        task = Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'error': 'Task not found'}, status=404)

    try:
        data = json.loads(request.body)
        dep_id = int(data['depends_on'])
        dep = Task.objects.get(pk=dep_id)
    except (json.JSONDecodeError, KeyError, ValueError, Task.DoesNotExist):
        return JsonResponse({'error': 'Invalid data'}, status=400)

    task.depends_on.remove(dep)
    return JsonResponse({'success': True})


@permission_required('issue', 'change')
@csrf_protect
@require_http_methods(['POST'])
def api_issue_relink(request, issue_id):
    """Move an issue to a different task (or unlink it)."""
    try:
        issue = Issue.objects.get(pk=issue_id)
    except Issue.DoesNotExist:
        return JsonResponse({'error': 'Issue not found'}, status=404)

    try:
        data = json.loads(request.body)
        task_id = data.get('task_id')  # None or int to unlink / link
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)

    issue.linked_tasks.clear()
    if task_id:
        try:
            task = Task.objects.get(pk=int(task_id))
            issue.linked_tasks.add(task)
        except Task.DoesNotExist:
            return JsonResponse({'error': 'Task not found'}, status=404)

    return JsonResponse({'success': True, 'issue_id': issue.pk, 'task_id': task_id})


# ── Version control ────────────────────────────────────────────────────────

@login_required
def project_history(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if not can_view_project(request.user, project):
        return forbidden_response(request, "You don't have permission to view this project.")
    versions = list(project.plan_versions.select_related('committed_by').all())
    versions_with_diff = [{'version': v, 'diff': v.diff_vs_previous} for v in versions]
    ctx = _project_ctx(project, 'history', user=request.user, extra={'versions_with_diff': versions_with_diff})
    return _htmx_tab(request, 'project/detail.html', 'project/_history.html', ctx)


@permission_required('projectplanversion', 'add', project_param='pk')
def project_commit_form(request, pk):
    project = get_object_or_404(Project, pk=pk)
    latest = project.plan_versions.first()
    return render(request, 'forms/_commit_form.html', {
        'form': CommitForm(),
        'project': project,
        'latest_version': latest,
    })


@permission_required('projectplanversion', 'add', project_param='pk')
@require_POST
def project_commit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    form = CommitForm(request.POST)
    if not form.is_valid():
        latest = project.plan_versions.first()
        return render(request, 'forms/_commit_form.html', {
            'form': form,
            'project': project,
            'latest_version': latest,
        })
    change_type = form.cleaned_data['change_type']
    comment = form.cleaned_data['change_comment']
    with transaction.atomic():
        major, minor = ProjectPlanVersion.next_version(project, change_type)
        
        # Get current tasks state before creating snapshot
        current_tasks = {t.id: t for t in project.tasks.all()}
        
        # Get previous version for comparison
        previous_version = project.plan_versions.first()
        prev_task_dates = {}
        if previous_version:
            for t in previous_version.task_snapshot:
                prev_task_dates[t['id']] = datetime.strptime(t['end'], '%Y-%m-%d').date()
        
        # Create the new version
        version = ProjectPlanVersion.objects.create(
            project=project,
            version_major=major,
            version_minor=minor,
            version_label=f"{major}.{minor}",
            change_type=change_type,
            change_comment=comment,
            committed_by=request.user,
            task_snapshot=ProjectPlanVersion.snapshot_project(project),
        )
        
        # Detect date changes and create records
        from .models import TaskDueDateChange
        for task_id, task in current_tasks.items():
            if task_id in prev_task_dates:
                prev_end = prev_task_dates[task_id]
                if prev_end != task.end:
                    TaskDueDateChange.objects.create(
                        task=task,
                        version=version,
                        previous_end=prev_end,
                        new_end=task.end,
                    )
    
    return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'versionCommitted': True})})


@permission_required('projectplanversion', 'add', project_param='pk')
@require_POST
def project_version_restore(request, pk, vid):
    project = get_object_or_404(Project, pk=pk)
    version = get_object_or_404(ProjectPlanVersion, pk=vid, project=project)

    with transaction.atomic():
        # Drop all current tasks (clears M2M: depends_on, linked_issues, linked_nre)
        project.tasks.all().delete()

        # Reconcile milestones: keep existing ones that appear in snapshot, create missing ones
        snapshot_section_names = {t['section'] for t in version.task_snapshot}
        project.milestones.exclude(name__in=snapshot_section_names).delete()
        section_map = {}
        for t in version.task_snapshot:
            name = t['section']
            if name not in section_map:
                ms, _ = Milestone.objects.get_or_create(
                    project=project, name=name,
                    defaults={'sort_order': 0}
                )
                section_map[name] = ms

        # Create tasks, mapping old snapshot IDs → new Task instances
        old_to_new = {}
        for t in version.task_snapshot:
            stage = None
            if t.get('stage_id'):
                stage = BuildStage.objects.filter(pk=t['stage_id'], project=project).first()
            new_task = Task.objects.create(
                project=project,
                milestone=section_map[t['section']],
                name=t['name'],
                remark=t.get('remark', ''),
                who=t.get('who', 'TBD'),
                days=t.get('days', 1),
                start=datetime.strptime(t['start'], '%Y-%m-%d').date(),
                end=datetime.strptime(t['end'], '%Y-%m-%d').date(),
                status=t.get('status', 'open'),
                stage=stage,
                sort_order=t.get('sort_order', 0),
            )
            old_to_new[t['id']] = new_task

        # Restore depends_on relationships using the old→new mapping
        for t in version.task_snapshot:
            for dep_old_id in t.get('depends_on', []):
                if dep_old_id in old_to_new:
                    old_to_new[t['id']].depends_on.add(old_to_new[dep_old_id])

    return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({
        'versionCommitted': True,
        'show-toast': {'message': f'Restored to v{version.version_label} successfully', 'type': 'success'},
    })})


@login_required
def project_version_detail(request, pk, vid):
    project = get_object_or_404(Project, pk=pk)
    version = get_object_or_404(ProjectPlanVersion, pk=vid, project=project)
    # Group snapshot tasks by section name
    tasks_by_section = {}
    for t in version.task_snapshot:
        section = t.get('section', 'Uncategorised')
        tasks_by_section.setdefault(section, []).append(t)
    return render(request, 'forms/_version_detail.html', {
        'project': project,
        'version': version,
        'tasks_by_section': tasks_by_section,
    })


# ── Power Automate Webhooks ───────────────────────────────────────────────────

@permission_required('webhookconfig', 'view')
def webhook_list(request):
    webhooks = WebhookConfig.objects.select_related('project').all()
    return render(request, 'webhooks/list.html', {
        'webhooks': webhooks,
        'event_choices': WebhookConfig.EVENT_CHOICES,
    })


@permission_required('webhookconfig', 'add')
def webhook_create(request):
    from .forms import WebhookConfigForm
    if request.method == 'POST':
        form = WebhookConfigForm(request.POST)
        if form.is_valid():
            wh = form.save(commit=False)
            wh.generate_token()
            wh.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': '/webhooks/'})
            return redirect('webhook-list')
    else:
        form = WebhookConfigForm()
    return render(request, 'forms/_webhook_form.html', {'form': form})


@permission_required('webhookconfig', 'change')
def webhook_edit(request, wid):
    from .forms import WebhookConfigForm
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    if request.method == 'POST':
        form = WebhookConfigForm(request.POST, instance=webhook)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': '/webhooks/'})
            return redirect('webhook-list')
    else:
        form = WebhookConfigForm(instance=webhook)
    return render(request, 'forms/_webhook_form.html', {'form': form, 'webhook': webhook})


@permission_required('webhookconfig', 'delete')
@require_POST
def webhook_delete(request, wid):
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    webhook.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': '/webhooks/'})
    return redirect('webhook-list')


@csrf_exempt
@require_POST
def webhook_pa_subscribe(request, wid, token):
    """
    Called by Power Automate's HTTP Webhook trigger to register its callback URL.
    PA sends: POST {"callbackUrl": "https://prod-xx.logic.azure.com/..."}
    We store that callbackUrl so we can fire events to it later.
    No login/CSRF — this is an external call from Power Automate.
    """
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    if webhook.pa_token != token or not token:
        return JsonResponse({'error': 'Invalid token'}, status=403)
    try:
        body = json.loads(request.body)
        callback_url = body.get('callbackUrl') or body.get('callback_url', '')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    if not callback_url:
        return JsonResponse({'error': 'callbackUrl missing from body'}, status=400)
    webhook.url = callback_url
    webhook.is_active = True
    webhook.last_error = ''
    webhook.save(update_fields=['url', 'is_active', 'last_error'])
    return JsonResponse({'status': 'subscribed'}, status=201)


@csrf_exempt
@require_POST
def webhook_pa_unsubscribe(request, wid, token):
    """
    Called by Power Automate when the flow is turned off or deleted.
    We deactivate the webhook rather than delete it.
    """
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    if webhook.pa_token != token or not token:
        return JsonResponse({'error': 'Invalid token'}, status=403)
    webhook.is_active = False
    webhook.save(update_fields=['is_active'])
    return JsonResponse({'status': 'unsubscribed'})


@permission_required('webhookconfig', 'change')
@require_POST
def webhook_test(request, wid):
    from .webhooks import _deliver
    import threading
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    payload = {
        'event': webhook.event,
        'test': True,
        'timestamp': timezone.now().isoformat(),
        'project': 'Test Project',
        'customer': 'Test Customer',
        'pgm': request.user.get_full_name() or request.user.username,
        'message': f'This is a test event from NPI Tracker for webhook "{webhook.name}".',
    }
    t = threading.Thread(target=_deliver, args=(webhook.pk, payload), daemon=True)
    t.start()
    if request.htmx:
        return HttpResponse(headers={
            'HX-Trigger': json.dumps({'show-toast': {'message': 'Test card sent', 'type': 'success'}})
        })
    return redirect('webhook-list')


@permission_required('webhookconfig', 'change')
@require_POST
def webhook_test_chat(request, wid):
    """Send a test card to a specific recipient (chat webhook with dynamic routing)."""
    from .webhooks import _deliver
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    recipient = request.POST.get('recipient', '').strip() or webhook.recipient
    if not recipient:
        if request.htmx:
            return HttpResponse(headers={
                'HX-Trigger': json.dumps({'show-toast': {'message': 'Enter a recipient email first', 'type': 'error'}})
            })
        return redirect('webhook-list')
    # Temporarily set recipient so _deliver wraps the card
    old_recipient = webhook.recipient
    webhook.recipient = recipient
    webhook.save(update_fields=['recipient'])
    payload = {
        'event': webhook.event,
        'test': True,
        'timestamp': timezone.now().isoformat(),
        'project': 'Test Project',
        'customer': 'Test Customer',
        'pgm': request.user.get_full_name() or request.user.username,
        'message': f'Chat test from NPI Tracker for webhook "{webhook.name}".',
    }
    t = threading.Thread(target=_deliver, args=(webhook.pk, payload), daemon=True)
    t.start()
    if request.htmx:
        return HttpResponse(headers={
            'HX-Trigger': json.dumps({'show-toast': {'message': f'Test card sent to {recipient}', 'type': 'success'}})
        })
    return redirect('webhook-list')


@permission_required('webhookconfig', 'change')
@require_POST
def webhook_test_text(request, wid):
    """Send a plain text ping — use this first to verify the URL is reachable."""
    from .webhooks import _deliver
    webhook = get_object_or_404(WebhookConfig, pk=wid)
    t = threading.Thread(target=_deliver, args=(webhook.pk, {}, True), daemon=True)
    t.start()
    if request.htmx:
        return HttpResponse(headers={
            'HX-Trigger': json.dumps({'show-toast': {'message': 'Plain text ping sent — check your Teams channel', 'type': 'success'}})
        })
    return redirect('webhook-list')


# ── Inbound Webhooks (receive events from Power Automate) ────────────────

@permission_required('inboundwebhook', 'view')
def inbound_webhook_list(request):
    webhooks = InboundWebhook.objects.select_related('project').all()
    return render(request, 'webhooks/inbound_list.html', {
        'webhooks': webhooks,
        'action_choices': InboundWebhook.ACTION_CHOICES,
    })


@permission_required('inboundwebhook', 'add')
def inbound_webhook_create(request):
    from .forms import InboundWebhookForm
    if request.method == 'POST':
        form = InboundWebhookForm(request.POST)
        if form.is_valid():
            wh = form.save(commit=False)
            wh.generate_token()
            wh.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': '/webhooks/inbound/'})
            return redirect('inbound-webhook-list')
    else:
        form = InboundWebhookForm()
    return render(request, 'forms/_inbound_webhook_form.html', {'form': form})


@permission_required('inboundwebhook', 'change')
def inbound_webhook_edit(request, wid):
    from .forms import InboundWebhookForm
    webhook = get_object_or_404(InboundWebhook, pk=wid)
    if request.method == 'POST':
        form = InboundWebhookForm(request.POST, instance=webhook)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': '/webhooks/inbound/'})
            return redirect('inbound-webhook-list')
    else:
        form = InboundWebhookForm(instance=webhook)
    return render(request, 'forms/_inbound_webhook_form.html', {'form': form, 'webhook': webhook})


@permission_required('inboundwebhook', 'delete')
@require_POST
def inbound_webhook_delete(request, wid):
    webhook = get_object_or_404(InboundWebhook, pk=wid)
    webhook.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': '/webhooks/inbound/'})
    return redirect('inbound-webhook-list')


@permission_required('inboundwebhook', 'change')
@require_POST
def inbound_webhook_regenerate(request, wid):
    """Regenerate the secret token for an inbound webhook."""
    webhook = get_object_or_404(InboundWebhook, pk=wid)
    webhook.generate_token()
    webhook.save(update_fields=['token'])
    if request.htmx:
        return HttpResponse(headers={
            'HX-Redirect': '/webhooks/inbound/',
        })
    return redirect('inbound-webhook-list')


# ── Task Due Date Changes ────────────────────────────────────────────────

@login_required
@require_POST
def acknowledge_date_change(request, change_id):
    """Mark a due date change as acknowledged by the current user."""
    from .models import TaskDueDateChange
    change = get_object_or_404(TaskDueDateChange, pk=change_id)
    
    # Only allow the assigned user or admin to acknowledge
    if change.task.assigned_to != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You can only acknowledge changes for your assigned tasks.")
    
    change.acknowledged = True
    change.acknowledged_at = timezone.now()
    change.acknowledged_by = request.user
    change.save(update_fields=['acknowledged', 'acknowledged_at', 'acknowledged_by'])
    
    if request.htmx:
        return HttpResponse(headers={
            'HX-Trigger': json.dumps({'show-toast': {'message': 'Date change acknowledged', 'type': 'success'}})
        })
    return redirect('my-tasks')


@login_required
@require_POST
def acknowledge_all_date_changes(request):
    """Mark all unacknowledged date changes for the current user as acknowledged."""
    from .models import TaskDueDateChange
    
    # Get all unacknowledged date changes for tasks assigned to this user
    changes = TaskDueDateChange.objects.filter(
        task__assigned_to=request.user,
        acknowledged=False
    )
    
    count = changes.count()
    now = timezone.now()
    
    for change in changes:
        change.acknowledged = True
        change.acknowledged_at = now
        change.acknowledged_by = request.user
        change.save(update_fields=['acknowledged', 'acknowledged_at', 'acknowledged_by'])
    
    if request.htmx:
        return HttpResponse(headers={
            'HX-Trigger': json.dumps({'show-toast': {'message': f'{count} date changes acknowledged', 'type': 'success'}})
        })
    return redirect('my-tasks')
