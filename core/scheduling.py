from __future__ import annotations
from collections import deque
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TaskTemplateSet, Project, BuildStage


class SchedulingError(Exception):
    pass


def _schedule_tasks_in_section(templates, forced_stage, section_start):
    """
    Kahn's topological sort for tasks within a single section.
    Returns list of dicts and the latest end date across all tasks.
    forced_stage: a BuildStage instance (or None) assigned to every task in this section.
    """
    if not templates:
        return [], section_start

    by_pk = {t.pk: t for t in templates}
    template_pks = set(by_pk.keys())

    in_degree = {t.pk: 0 for t in templates}
    dependents_of = {t.pk: [] for t in templates}

    for t in templates:
        for prereq in t.depends_on.all():
            if prereq.pk not in template_pks:
                continue
            in_degree[t.pk] += 1
            dependents_of[prereq.pk].append(t.pk)

    queue = deque(pk for pk, deg in in_degree.items() if deg == 0)
    finish_date = {}
    processed = 0
    result = []
    max_end = section_start

    while queue:
        pk = queue.popleft()
        processed += 1
        tmpl = by_pk[pk]

        prereq_ends = [
            finish_date[prereq.pk]
            for prereq in tmpl.depends_on.all()
            if prereq.pk in template_pks and prereq.pk in finish_date
        ]
        task_start = max(prereq_ends) + timedelta(days=1) if prereq_ends else section_start
        task_end = task_start + timedelta(days=max(tmpl.days - 1, 0))
        finish_date[pk] = task_end

        if task_end > max_end:
            max_end = task_end

        result.append({
            'template_pk': pk,
            'name': tmpl.name,
            'section': tmpl.section.name,
            'who': tmpl.who,
            'days': tmpl.days,
            'start': task_start,
            'end': task_end,
            'status': 'open',
            'stage': forced_stage,
            'sort_order': tmpl.sort_order,
        })

        for dep_pk in dependents_of[pk]:
            in_degree[dep_pk] -= 1
            if in_degree[dep_pk] == 0:
                queue.append(dep_pk)

    if processed != len(templates):
        section_name = templates[0].section.name if templates else '?'
        raise SchedulingError(
            f'Dependency cycle in section "{section_name}". '
            f'{len(templates) - processed} task(s) could not be scheduled.'
        )

    return result, max_end


def generate_tasks_from_template(
    template_set: "TaskTemplateSet",
    project: "Project",
    start_date: date,
    section_overrides: dict[int, date] | None = None,
    forced_stage: "BuildStage | None" = None,
) -> list[dict]:
    """
    Schedule all sections and their tasks.

    Section scheduling rules:
      - If section has a manual override date (from section_overrides), use that
      - Elif depends_on is set, start day after the referenced section's last task ends
      - Else start at start_date + day_offset

    Within each section, tasks are scheduled via Kahn's topological sort.
    """
    section_overrides = section_overrides or {}

    sections = list(
        template_set.sections
        .prefetch_related('tasks__depends_on', 'depends_on')
        .order_by('sort_order', 'id')
    )

    if not sections:
        return []

    all_results = []
    section_ends = {}  # Track end date of each section for dependencies

    for sec in sections:
        # Determine section start date
        if sec.pk in section_overrides:
            section_start = section_overrides[sec.pk]
        elif sec.depends_on and sec.depends_on.pk in section_ends:
            section_start = section_ends[sec.depends_on.pk] + timedelta(days=1)
        else:
            section_start = start_date + timedelta(days=sec.day_offset)

        templates = list(sec.tasks.prefetch_related('depends_on').order_by('sort_order', 'id'))
        section_results, section_end = _schedule_tasks_in_section(
            templates, forced_stage, section_start
        )

        all_results.extend(section_results)
        section_ends[sec.pk] = section_end

    return all_results
