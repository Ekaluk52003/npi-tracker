import json
from datetime import date, timedelta
from itertools import groupby
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from .models import Project, BuildStage, GateChecklistItem, ProjectSection, Task, Issue, TeamMember, NREItem, TaskTemplateSet
from .forms import ProjectForm, TaskForm, IssueForm, TeamMemberForm, NREItemForm, BuildStageForm, GateChecklistItemForm, ProjectSectionForm
from .scheduling import generate_tasks_from_template, SchedulingError


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
        'project_sections': list(project.sections.all()),
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
    tasks = project.tasks.select_related('stage', 'section').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section, group in groupby(tasks, key=lambda t: t.section_id):
        task_list = list(group)
        sections.append({
            'section': task_list[0].section.name if task_list else '',
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
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__section', 'stages'), pk=pk)
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage', 'section').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section_id, group in groupby(tasks, key=lambda t: t.section_id):
        task_list = list(group)
        sections.append({'section': task_list[0].section.name, 'tasks': task_list})
    ctx = _project_ctx(project, 'list', {
        'sections': sections,
        'stage_filter': stage_filter,
    })
    return _htmx_tab(request, 'project/detail.html', 'project/_list.html', ctx)


def project_milestones(request, pk):
    project = get_object_or_404(Project.objects.prefetch_related('tasks__stage', 'tasks__section', 'stages'), pk=pk)
    stage_filter = request.GET.get('stage', '')
    tasks = project.tasks.select_related('stage', 'section').all()
    if stage_filter and stage_filter.isdigit():
        tasks = tasks.filter(stage_id=int(stage_filter))
    sections = []
    for section_id, group in groupby(tasks, key=lambda t: t.section_id):
        task_list = list(group)
        total = len(task_list)
        done = sum(1 for t in task_list if t.status == 'done')
        starts = [t.start for t in task_list]
        ends = [t.end for t in task_list]
        sections.append({
            'section': task_list[0].section.name,
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


# ── Section CRUD ────────────────────────────────────────────────────────

def section_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectSectionForm(request.POST)
        if form.is_valid():
            section = form.save(commit=False)
            section.project = project
            if not section.sort_order:
                section.sort_order = project.sections.count()
            section.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = ProjectSectionForm(initial={'sort_order': project.sections.count()})
    return render(request, 'forms/_section_form.html', {'form': form, 'project': project})


def section_edit(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    section = get_object_or_404(ProjectSection, pk=sid, project=project)
    if request.method == 'POST':
        form = ProjectSectionForm(request.POST, instance=section)
        if form.is_valid():
            form.save()
            if request.htmx:
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
            return redirect('project-gantt', pk=pk)
    else:
        form = ProjectSectionForm(instance=section)
    return render(request, 'forms/_section_form.html', {'form': form, 'project': project, 'section': section})


def section_delete(request, pk, sid):
    project = get_object_or_404(Project, pk=pk)
    section = get_object_or_404(ProjectSection, pk=sid, project=project)
    section.delete()
    if request.htmx:
        return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/gantt/')})
    return redirect('project-gantt', pk=pk)


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
                return HttpResponse(headers={'HX-Redirect': request.META.get('HTTP_REFERER', f'/project/{pk}/issues/')})
            return redirect('project-issues', pk=pk)
    else:
        form = IssueForm(project=project, initial=initial)
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


# ── Task Issues Modal ───────────────────────────────────────────────────

def task_issues_modal(request, pk, tid):
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=tid, project=project)
    issues = task.linked_issues.exclude(status='resolved')
    return render(request, 'forms/_task_issues_modal.html', {
        'project': project,
        'task': task,
        'issues': issues,
    })


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


# ── Apply Task Template ────────────────────────────────────────────────

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

        # Parse per-section date overrides from POST (section PKs are globally unique)
        section_overrides = {}
        for key, val in request.POST.items():
            if key.startswith('section_date_') and val:
                try:
                    sec_pk = int(key.replace('section_date_', ''))
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

                section_cache = {}
                base_section_order = project.sections.count()
                for d in all_task_dicts:
                    sec_name = d['section']
                    if sec_name not in section_cache:
                        ps, _ = ProjectSection.objects.get_or_create(
                            project=project, name=sec_name,
                            defaults={'sort_order': base_section_order + len(section_cache)},
                        )
                        section_cache[sec_name] = ps

                base_sort = project.tasks.count()
                tasks_to_create = []
                for i, d in enumerate(all_task_dicts):
                    d.pop('template_pk', None)
                    d['sort_order'] = base_sort + i
                    d['section'] = section_cache[d['section']]
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


def template_preview(request, pk, set_pk):
    project = get_object_or_404(Project, pk=pk)
    template_set = get_object_or_404(TaskTemplateSet, pk=set_pk)
    start_date_str = request.GET.get('start_date', '')
    try:
        preview_start = date.fromisoformat(start_date_str)
    except (ValueError, TypeError):
        preview_start = project.start_date

    # Parse per-section date overrides from GET
    section_overrides = {}
    for key, val in request.GET.items():
        if key.startswith('section_date_') and val:
            try:
                sec_pk = int(key.replace('section_date_', ''))
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
    sections_qs = template_set.sections.select_related('depends_on').prefetch_related('tasks__depends_on').order_by('sort_order', 'id')
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

    has_error = len(task_dicts) == 0 and template_set.sections.exists()

    return render(request, 'forms/_template_preview.html', {
        'project': project,
        'template_set': template_set,
        'sections': sections,
        'start_date': preview_start,
        'has_error': has_error,
    })


# ── API Endpoints ────────────────────────────────────────────────────────────

@csrf_protect
@require_http_methods(['PATCH'])
def api_task_update(request, task_id):
    """Update task dates (start/end) via API."""
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
        task.save(update_fields=['start', 'end'])
        return JsonResponse({'success': True, 'start': task.start.isoformat(), 'end': task.end.isoformat()})
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': f'Invalid data: {str(e)}'}, status=400)
