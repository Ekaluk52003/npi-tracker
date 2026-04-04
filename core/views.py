import json
from datetime import date, timedelta
from itertools import groupby
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from .models import Project, BuildStage, GateChecklistItem, Task, Issue, TeamMember, NREItem
from .forms import ProjectForm, TaskForm, IssueForm, TeamMemberForm, NREItemForm, BuildStageForm, GateChecklistItemForm


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
    ctx = {
        'project': project,
        'active_tab': tab,
        'open_issue_count': project.issues.exclude(status='resolved').count(),
        'nre_no_po_count': project.nre_items.filter(po_status='no-po').count(),
        'project_stages': list(project.stages.all()),
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


def _gantt_data_for_project(project, stage_filter=''):
    tasks = project.tasks.select_related('stage').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section, group in groupby(tasks, key=lambda t: t.section):
        task_list = list(group)
        sections.append({
            'section': section,
            'tasks': [{
                'id': t.pk,
                'name': t.name,
                'who': t.who,
                'days': t.days,
                'start': t.start.isoformat(),
                'end': t.end.isoformat(),
                'status': t.status,
                'stage': t.stage.name if t.stage else '',
                'stage_color': t.stage.color if t.stage else '',
                'remark': t.remark[:60] if t.remark else '',
                'open_issues': t.linked_issues.exclude(status='resolved').count(),
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

def portfolio(request):
    projects = Project.objects.prefetch_related('stages', 'tasks', 'issues', 'nre_items').all()
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
        'page_title': 'Portfolio Overview',
        'project_rows': project_rows,
        'portfolio_gantt_data': gantt_data,
    }
    return _htmx(request, 'portfolio/portfolio.html', 'portfolio/_content.html', ctx)


def project_issues_modal(request, pk):
    project = get_object_or_404(Project, pk=pk)
    issues = project.issues.select_related('stage').all()
    return render(request, 'portfolio/_issues_modal.html', {'project': project, 'issues': issues})


# ── Project Detail Tabs ──────────────────────────────────────────────────

def project_detail(request, pk):
    return redirect('project-gantt', pk=pk)


def project_gantt(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'stages', 'issues'), pk=pk)
    stage_filter = request.GET.get('stage', '')
    gantt_data = _gantt_data_for_project(project, stage_filter)
    ctx = _project_ctx(project, 'gantt', {
        'gantt_data': gantt_data,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_gantt.html', ctx)


def project_list(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'stages'), pk=pk)
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section, group in groupby(tasks, key=lambda t: t.section):
        sections.append({'section': section, 'tasks': list(group)})
    ctx = _project_ctx(project, 'list', {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_list.html', ctx)


def project_milestones(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'stages'), pk=pk)
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section, group in groupby(tasks, key=lambda t: t.section):
        task_list = list(group)
        total = len(task_list)
        done = sum(1 for t in task_list if t.status == 'done')
        starts = [t.start for t in task_list]
        ends = [t.end for t in task_list]
        sections.append({
            'section': section,
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


def project_team(request, pk):
    project = get_object_or_404(Project, pk=pk)
    members = project.team_members.all()
    for m in members:
        m.task_count = project.tasks.filter(who__icontains=m.name).count()
        if not m.task_count and m.company:
            m.task_count = project.tasks.filter(who__icontains=m.company).count()
    ctx = _project_ctx(project, 'team', {'members': members})
    return _htmx_tab(request, 'project/detail.html', 'project/_team.html', ctx)


def project_stages(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('stages__gate_items', 'tasks__stage', 'issues__stage', 'nre_items__stage'), pk=pk)
    stages = list(project.stages.all())
    for s in stages:
        s.gate = s.gate_readiness
        s.tasks_done = s.tasks.filter(status='done').count()
        s.tasks_total = s.tasks.count()
    ctx = _project_ctx(project, 'stages', {'stages': stages})
    return _htmx_tab(request, 'project/detail.html', 'project/_stages.html', ctx)


def project_nre(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('nre_items__stage', 'tasks', 'stages'), pk=pk)
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


def project_issues(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('issues__linked_tasks', 'issues__stage', 'stages'), pk=pk)
    open_issues = project.issues.select_related('stage').exclude(status='resolved')
    resolved_issues = project.issues.select_related('stage').filter(status='resolved')
    ctx = _project_ctx(project, 'issues', {
        'open_issues': open_issues,
        'resolved_issues': resolved_issues,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_issues.html', ctx)


# ── Project CRUD ─────────────────────────────────────────────────────────

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


# ── Task CRUD ────────────────────────────────────────────────────────────

def task_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = TaskForm(request.POST, project=project)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = project
            task.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = TaskForm(project=project, initial={'start': date.today(), 'end': date.today() + timedelta(days=7)})
    return render(request, 'forms/_task_form.html', {'form': form, 'project': project})


def task_edit(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task, project=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = TaskForm(instance=task, project=project)
    return render(request, 'forms/_task_form.html', {'form': form, 'project': project, 'task': task})


def task_delete(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    task.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
    return redirect('project-gantt', pk=pk)


# ── Issue CRUD ───────────────────────────────────────────────────────────

def issue_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = IssueForm(request.POST, project=project)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.project = project
            issue.save()
            form.save_m2m()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/issues/'})
            return redirect('project-issues', pk=pk)
    else:
        form = IssueForm(project=project)
    return render(request, 'forms/_issue_form.html', {'form': form, 'project': project})


def issue_edit(request, pk, iid):
    project = get_object_or_404(Project, pk=pk)
    issue = get_object_or_404(Issue, pk=iid, project=project)
    if request.method == 'POST':
        form = IssueForm(request.POST, instance=issue, project=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/issues/'})
            return redirect('project-issues', pk=pk)
    else:
        form = IssueForm(instance=issue, project=project)
    return render(request, 'forms/_issue_form.html', {'form': form, 'project': project, 'issue': issue})


def issue_delete(request, pk, iid):
    project = get_object_or_404(Project, pk=pk)
    issue = get_object_or_404(Issue, pk=iid, project=project)
    issue.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/issues/'})
    return redirect('project-issues', pk=pk)


# ── Team CRUD ────────────────────────────────────────────────────────────

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


def member_delete(request, pk, mid):
    project = get_object_or_404(Project, pk=pk)
    member = get_object_or_404(TeamMember, pk=mid, project=project)
    member.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/team/'})
    return redirect('project-team', pk=pk)


# ── NRE CRUD ─────────────────────────────────────────────────────────────

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


def nre_delete(request, pk, nid):
    project = get_object_or_404(Project, pk=pk)
    nre = get_object_or_404(NREItem, pk=nid, project=project)
    nre.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/nre/'})
    return redirect('project-nre', pk=pk)


# ── Build Stage CRUD ────────────────────────────────────────────────────

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


def stage_edit(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    gate_form = GateChecklistItemForm()
    if request.method == 'POST':
        if 'add_gate_item' in request.POST:
            gf = GateChecklistItemForm(request.POST)
            if gf.is_valid():
                item = gf.save(commit=False)
                item.stage = stage
                item.sort_order = stage.gate_items.count()
                item.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
            return redirect('project-stages', pk=pk)
        if 'delete_gate_item' in request.POST:
            gid = request.POST.get('delete_gate_item')
            GateChecklistItem.objects.filter(pk=gid, stage=stage).delete()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
            return redirect('project-stages', pk=pk)
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


def stage_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    stage.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
    return redirect('project-stages', pk=pk)


def gate_toggle(request, pk, sid, gid):
    project = get_object_or_404(Project, pk=pk)
    stage = get_object_or_404(BuildStage, pk=sid, project=project)
    item = get_object_or_404(GateChecklistItem, pk=gid, stage=stage)
    item.checked = not item.checked
    item.save()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': f'/project/{pk}/stages/'})
    return redirect('project-stages', pk=pk)
