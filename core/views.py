import json
import math
import threading
from collections import defaultdict, deque
from datetime import date, timedelta, datetime
from itertools import groupby
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction
from .models import Project, BuildStage, GateChecklistItem, Milestone, Task, Issue, TeamMember, NREItem, TaskTemplateSet, ProjectPlanVersion, WebhookConfig, InboundWebhook
from .forms import ProjectForm, TaskForm, IssueForm, TeamMemberForm, NREItemForm, BuildStageForm, GateChecklistItemForm, MilestoneForm, CommitForm
from .scheduling import generate_tasks_from_template, SchedulingError
from .permissions import role_required, can_view_project, can_edit_issue, get_project_queryset, is_pm


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


def _project_ctx(project, tab, extra=None):
    latest_version = project.plan_versions.first()
    ctx = {
        'project': project,
        'active_tab': tab,
        'open_issue_count': project.issues.exclude(status='resolved').count(),
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


def _gantt_data_from_snapshot(version, project):
    stage_colors = {s.name: s.color for s in project.stages.all()}
    sections_map = {}
    for t in version.task_snapshot:
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
            } for t in tasks],
        }
        for sec_name, tasks in sections_map.items()
    ]
    starts = [t['start'] for t in version.task_snapshot]
    ends = [t['end'] for t in version.task_snapshot]
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


def _gantt_data_for_project(project, stage_filter=''):
    tasks = project.tasks.select_related('stage', 'milestone', 'assigned_to').prefetch_related('linked_nre', 'depends_on', 'linked_issues').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        sections.append({
            'milestone': task_list[0].milestone.name if task_list else '',
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
            } for t in task_list],
        })
    all_tasks = project.tasks.all()
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
        return HttpResponseForbidden("You don't have permission to view this project.")
    issues = project.issues.select_related('stage').all()
    return render(request, 'portfolio/_issues_modal.html', {'project': project, 'issues': issues})


# ── My Tasks ────────────────────────────────────────────────────────────

@login_required
def my_tasks(request):
    user = request.user

    # Tasks assigned to the current user that are not done
    base_qs = Task.objects.filter(
        assigned_to=user,
    ).exclude(status='done').select_related('project', 'milestone', 'stage').prefetch_related('depends_on')

    # "Ready to start": open, with no incomplete dependencies
    has_pending_dep_ids = Task.objects.filter(
        assigned_to=user,
        status='open',
        depends_on__status__in=['open', 'inprogress', 'blocked'],
    ).values_list('id', flat=True).distinct()

    ready = base_qs.filter(status='open').exclude(id__in=has_pending_dep_ids)
    in_progress = base_qs.filter(status='inprogress')
    blocked = base_qs.filter(status='blocked')
    waiting = base_qs.filter(status='open').filter(id__in=has_pending_dep_ids)

    # Issues assigned to the current user (not resolved)
    my_issues = Issue.objects.filter(
        assigned_to=user,
    ).exclude(status='resolved').select_related('project', 'stage').order_by('severity', 'status')

    ctx = {
        'ready': ready,
        'in_progress': in_progress,
        'blocked': blocked,
        'waiting': waiting,
        'my_issues': my_issues,
        'today': date.today(),
        'active_my_tasks': True,
    }
    return _htmx(request, 'my_tasks_page.html', 'my_tasks.html', ctx)


# ── Project Detail Tabs ──────────────────────────────────────────────────

@login_required
def project_detail(request, pk):
    return redirect('project-gantt', pk=pk)


@login_required
def project_gantt(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__linked_nre', 'stages', 'issues'), pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    version_id = request.GET.get('version', '')
    compare_version_id = request.GET.get('compare_version', '')
    viewing_version = None
    compare_version = None
    compare_data = None

    if version_id and version_id.isdigit():
        viewing_version = get_object_or_404(ProjectPlanVersion, pk=int(version_id), project=project)
        gantt_data = _gantt_data_from_snapshot(viewing_version, project)
    else:
        gantt_data = _gantt_data_for_project(project, stage_filter)

    # Handle comparison version for overlay display
    if compare_version_id and compare_version_id.isdigit():
        compare_version = get_object_or_404(ProjectPlanVersion, pk=int(compare_version_id), project=project)
        compare_data = _gantt_data_from_snapshot(compare_version, project)

    ctx = _project_ctx(project, 'gantt', {
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
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__milestone', 'tasks__linked_nre', 'stages'), pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage', 'milestone').prefetch_related('linked_nre').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        sections.append({'milestone': task_list[0].milestone.name, 'tasks': task_list})
    ctx = _project_ctx(project, 'list', {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_list.html', ctx)


@login_required
def project_milestones(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__milestone', 'stages'), pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage', 'milestone').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for milestone_id, group in groupby(tasks, key=lambda t: t.milestone_id):
        task_list = list(group)
        total = len(task_list)
        done = sum(1 for t in task_list if t.status == 'done')
        starts = [t.start for t in task_list]
        ends = [t.end for t in task_list]
        sections.append({
            'milestone': task_list[0].milestone.name,
            'tasks': task_list,
            'total': total,
            'done': done,
            'pct': round(done / total * 100) if total else 0,
            'start': min(starts) if starts else None,
            'end': max(ends) if ends else None,
        })
    ctx = _project_ctx(project, 'milestones', {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_milestones.html', ctx)


@login_required
def project_team(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    members = project.team_members.all()
    for m in members:
        # For internal members, count tasks assigned to their user account
        if m.member_type == 'internal' and m.user:
            m.task_count = project.tasks.filter(assigned_to=m.user).count()
            m.issue_count = project.issues.filter(assigned_to=m.user).count()
        else:
            # For external members, fall back to who/owner field matching
            m.task_count = project.tasks.filter(who__icontains=m.name).count()
            if not m.task_count and m.company:
                m.task_count = project.tasks.filter(who__icontains=m.company).count()
            m.issue_count = project.issues.filter(owner__icontains=m.name).count()
            if not m.issue_count and m.company:
                m.issue_count = project.issues.filter(owner__icontains=m.company).count()
    ctx = _project_ctx(project, 'team', {'members': members})
    return _htmx_tab(request, 'project/detail.html', 'project/_team.html', ctx)


@login_required
def project_stages(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('stages__gate_items', 'tasks__stage', 'issues__stage', 'nre_items__stage'), pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    stages = list(project.stages.all())
    for s in stages:
        s.gate = s.gate_readiness
        s.tasks_done = s.tasks.filter(status='done').count()
        s.tasks_total = s.tasks.count()
    ctx = _project_ctx(project, 'stages', {'stages': stages})
    return _htmx_tab(request, 'project/detail.html', 'project/_stages.html', ctx)


@login_required
def project_nre(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('nre_items__stage', 'tasks', 'stages'), pk=pk)
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    items = project.nre_items.select_related('stage').all()
    categories = []
    for cat, group in groupby(items, key=lambda n: n.category):
        cat_items = list(group)
        categories.append({'category': cat, 'items': cat_items, 'count': len(cat_items)})
    total = sum(n.total_cost for n in items)
    covered = sum(n.total_cost for n in items if n.po_status != 'no-po')
    paid = sum(n.total_cost for n in items if n.po_status == 'paid')
    no_po = items.filter(po_status='no-po').count()
    ctx = _project_ctx(project, 'nre', {
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
    project = get_object_or_404(
        Project.objects.prefetch_related(
            'tasks__stage', 'tasks__milestone', 'tasks__linked_issues', 'stages',
        ),
        pk=pk,
    )
    if not can_view_project(request.user, project):
        return HttpResponseForbidden("You don't have permission to view this project.")
    tasks = list(project.tasks.exclude(status='done').select_related('stage', 'milestone'))
    task_ids = {t.pk for t in tasks}

    # Build adjacency from M2M through table in one query
    through = Task.depends_on.through
    edges = through.objects.filter(
        from_task_id__in=task_ids, to_task_id__in=task_ids,
    ).values_list('from_task_id', 'to_task_id')

    # from_task depends_on to_task  =>  to_task's dependents include from_task
    dependents_map = defaultdict(set)
    for from_id, to_id in edges:
        dependents_map[to_id].add(from_id)

    def _total_downstream(tid):
        visited = set()
        queue = deque(dependents_map.get(tid, set()))
        while queue:
            curr = queue.popleft()
            if curr in visited:
                continue
            visited.add(curr)
            queue.extend(dependents_map.get(curr, set()) - visited)
        return len(visited)

    # Compute raw scores
    scored = []
    for t in tasks:
        d = len(dependents_map.get(t.pk, set()))
        p = _total_downstream(t.pk)
        dur = t.days
        score = (d * W_DIRECT) + (p * W_DOWNSTREAM) + (dur * W_DURATION)
        scored.append({
            'task': t,
            'd': d, 'p': p, 't': dur, 'score': score, 'cis': 0,
        })

    # Normalize CIS 1-5 per build stage
    by_stage = defaultdict(list)
    for s in scored:
        stage_name = s['task'].stage.name if s['task'].stage else '__none__'
        by_stage[stage_name].append(s)

    stage_order_map = {}
    for idx, stage in enumerate(project.stages.all()):
        stage_order_map[stage.name] = idx

    for stage_name, group in by_stage.items():
        raw_scores = [g['score'] for g in group]
        mn, mx = min(raw_scores), max(raw_scores)
        for g in group:
            if mx == mn:
                g['cis'] = 3
            else:
                g['cis'] = round(1 + ((g['score'] - mn) / (mx - mn)) * 4)

    # Sort: by stage order, then CIS desc within stage
    scored.sort(key=lambda s: (
        stage_order_map.get(s['task'].stage.name if s['task'].stage else '', 999),
        -s['cis'],
        -s['score'],
    ))

    # Build stage groups for the header band
    stage_groups = []
    prev_stage = None
    for s in scored:
        sname = s['task'].stage.name if s['task'].stage else 'No Stage'
        scolor = s['task'].stage.color if s['task'].stage else '#666'
        if sname != prev_stage:
            stage_groups.append({'stage': sname, 'color': scolor, 'count': 1})
            prev_stage = sname
        else:
            stage_groups[-1]['count'] += 1

    # Attach open issues per task
    for s in scored:
        s['open_issues'] = list(s['task'].linked_issues.exclude(status='resolved'))
        s['issue_count'] = len(s['open_issues'])

    # Unlinked issues (not linked to any active task)
    all_issues = list(project.issues.exclude(status='resolved').prefetch_related('linked_tasks'))
    unlinked = [i for i in all_issues if not i.linked_tasks.exclude(status='done').exists()]

    today = date.today()

    ctx = _project_ctx(project, 'critical-index', {
        'scored_tasks': scored,
        'stage_groups_json': json.dumps(stage_groups),
        'unlinked_issues': unlinked,
        'total_issue_count': len(all_issues),
        'unlinked_count': len(unlinked),
        'today': today,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_critical_index.html', ctx)


# ── Project CRUD ─────────────────────────────────────────────────────────

@role_required('pm')
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            # Parse dynamic stages from POST
            stages_json = request.POST.get('stages_json', '')
            if stages_json:
                try:
                    stages_list = json.loads(stages_json)
                    for i, s in enumerate(stages_list):
                        if s.get('name', '').strip():
                            BuildStage.objects.create(
                                project=project,
                                name=s['name'].strip(),
                                full_name=s.get('full_name', '').strip(),
                                color=s.get('color', '#3b82f6'),
                                sort_order=i + 1,
                            )
                except (json.JSONDecodeError, TypeError):
                    pass
            # If no stages were added, create defaults
            if not project.stages.exists():
                project.create_default_stages()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{project.pk}/gantt/'})
            return redirect('project-gantt', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'forms/_project_form.html', {'form': form})


@role_required('pm')
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

@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
def section_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    milestone = get_object_or_404(Milestone, pk=sid, project=project)
    milestone.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
    return redirect('project-gantt', pk=pk)


# ── Task CRUD ────────────────────────────────────────────────────────────

@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
def task_delete(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    task.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'taskSaved': True, 'taskDeleted': {'id': tid}})})
    return redirect('project-gantt', pk=pk)


# ── Issue CRUD ───────────────────────────────────────────────────────────

@role_required('pm')
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
        return HttpResponseForbidden("You don't have permission to edit this issue.")
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


@role_required('pm')
def issue_delete(request, pk, iid):
    project = get_object_or_404(Project, pk=pk)
    issue = get_object_or_404(Issue, pk=iid, project=project)
    issue.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/critical-index/'})
    return redirect('project-critical-index', pk=pk)


# ── Team CRUD ────────────────────────────────────────────────────────────

@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
def member_delete(request, pk, mid):
    project = get_object_or_404(Project, pk=pk)
    member = get_object_or_404(TeamMember, pk=mid, project=project)
    member.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/team/'})
    return redirect('project-team', pk=pk)


# ── NRE CRUD ─────────────────────────────────────────────────────────────

@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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
        return HttpResponseForbidden("You don't have permission to view this project.")
    task = get_object_or_404(Task, pk=tid, project=project)
    issues = task.linked_issues.exclude(status='resolved')
    return render(request, 'forms/_task_issues_modal.html', {
        'project': project,
        'task': task,
        'issues': issues,
    })


# ── Build Stage CRUD ────────────────────────────────────────────────────

@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
def stage_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    stage.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
    return redirect('project-stages', pk=pk)


@role_required('pm')
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

@role_required('pm')
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


@role_required('pm')
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

@role_required('pm')
@csrf_protect
@require_http_methods(['PATCH'])
def api_task_update(request, task_id):
    """Update task dates (start/end) via API. Cascades to direct dependents."""
    try:
        task = Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'error': 'Task not found'}, status=404)

    try:
        data = json.loads(request.body)
        if 'start' in data:
            task.start = date.fromisoformat(data['start'])
        if 'end' in data:
            task.end = date.fromisoformat(data['end'])
        task.save()
        cascaded = _cascade_dependents(task)
        return JsonResponse({
            'success': True,
            'start': task.start.isoformat(),
            'end': task.end.isoformat(),
            'days': task.days,
            'cascaded': cascaded,
        })
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': f'Invalid data: {str(e)}'}, status=400)


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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
        return HttpResponseForbidden("You don't have permission to view this project.")
    versions = list(project.plan_versions.select_related('committed_by').all())
    versions_with_diff = [{'version': v, 'diff': v.diff_vs_previous} for v in versions]
    ctx = _project_ctx(project, 'history', {'versions_with_diff': versions_with_diff})
    return _htmx_tab(request, 'project/detail.html', 'project/_history.html', ctx)


@role_required('pm')
def project_commit_form(request, pk):
    project = get_object_or_404(Project, pk=pk)
    latest = project.plan_versions.first()
    return render(request, 'forms/_commit_form.html', {
        'form': CommitForm(),
        'project': project,
        'latest_version': latest,
    })


@role_required('pm')
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
        ProjectPlanVersion.objects.create(
            project=project,
            version_major=major,
            version_minor=minor,
            version_label=f"{major}.{minor}",
            change_type=change_type,
            change_comment=comment,
            committed_by=request.user,
            task_snapshot=ProjectPlanVersion.snapshot_project(project),
        )
    return HttpResponse(headers={'HX-Trigger-After-Settle': json.dumps({'versionCommitted': True})})


@role_required('pm')
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

@role_required('pm')
def webhook_list(request):
    webhooks = WebhookConfig.objects.select_related('project').all()
    return render(request, 'webhooks/list.html', {
        'webhooks': webhooks,
        'event_choices': WebhookConfig.EVENT_CHOICES,
    })


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
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

@role_required('pm')
def inbound_webhook_list(request):
    webhooks = InboundWebhook.objects.select_related('project').all()
    return render(request, 'webhooks/inbound_list.html', {
        'webhooks': webhooks,
        'action_choices': InboundWebhook.ACTION_CHOICES,
    })


@role_required('pm')
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


@role_required('pm')
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


@role_required('pm')
@require_POST
def inbound_webhook_delete(request, wid):
    webhook = get_object_or_404(InboundWebhook, pk=wid)
    webhook.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': '/webhooks/inbound/'})
    return redirect('inbound-webhook-list')


@role_required('pm')
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
