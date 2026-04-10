from django.conf import settings
from django.db import models
from datetime import date


class Project(models.Model):
    CURRENCY_CHOICES = [('THB', 'THB'), ('USD', 'USD'), ('EUR', 'EUR')]

    name = models.CharField(max_length=200)
    pgm = models.CharField(max_length=100, verbose_name='Program Manager')
    customer = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    color = models.CharField(max_length=7, default='#34B27B')
    annual_volume = models.IntegerField(null=True, blank=True)
    annual_revenue = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='THB')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def overall_status(self):
        if self.issues.filter(severity='critical').exclude(status='resolved').exists():
            return 'blocked'
        if self.tasks.filter(status='inprogress').exists():
            return 'inprogress'
        if self.tasks.exists() and not self.tasks.exclude(status='done').exists():
            return 'done'
        return 'open'

    @property
    def overall_status_label(self):
        return {'open': 'Planning', 'inprogress': 'Active', 'done': 'Complete', 'blocked': 'Blocked'}[self.overall_status]

    @property
    def current_stage(self):
        for status in ['in-progress', 'ready', 'planned']:
            stage = self.stages.filter(status=status).order_by('sort_order').first()
            if stage:
                return stage
        return None

    @property
    def duration_months(self):
        if self.start_date and self.end_date:
            return round((self.end_date - self.start_date).days / 30)
        return 0

    @property
    def duration_label(self):
        m = self.duration_months
        if m >= 12:
            return f"{m/12:.1f} yr"
        return f"{m} mo"

    @property
    def task_progress(self):
        total = self.tasks.count()
        if not total:
            return {'total': 0, 'done': 0, 'pct': 0}
        done = self.tasks.filter(status='done').count()
        return {'total': total, 'done': done, 'pct': round(done / total * 100)}

    @property
    def open_issue_count(self):
        return self.issues.exclude(status='resolved').count()

    @property
    def has_critical_issue(self):
        return self.issues.filter(severity='critical').exclude(status='resolved').exists()

    @property
    def nre_total(self):
        return sum(n.cost * n.qty for n in self.nre_items.all())

    @property
    def nre_no_po_count(self):
        return self.nre_items.filter(po_status='no-po').count()

    @property
    def nre_no_po_amount(self):
        return sum(n.cost * n.qty for n in self.nre_items.filter(po_status='no-po'))

    @property
    def currency_symbol(self):
        return {'THB': '฿', 'USD': '$', 'EUR': '€'}.get(self.currency, self.currency)

    def create_default_stages(self):
        defaults = [
            ('ETB', 'External Test Build', '#f59e0b', 1),
            ('PS', 'Pre-Series Build', '#8b5cf6', 2),
            ('FAS', 'First Article Sample', '#06b6d4', 3),
        ]
        for name, full_name, color, order in defaults:
            BuildStage.objects.get_or_create(
                project=self, name=name,
                defaults={'full_name': full_name, 'color': color, 'sort_order': order}
            )


class BuildStage(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'), ('ready', 'Ready'), ('in-progress', 'In Progress'),
        ('completed', 'Completed'), ('on-hold', 'On Hold'),
    ]
    APPROVAL_CHOICES = [
        ('pending', 'Pending'), ('approved', 'Approved'),
        ('conditional', 'Conditional'), ('rejected', 'Rejected'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='stages')
    name = models.CharField(max_length=50)
    full_name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default='#3b82f6')
    planned_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    build_qty = models.IntegerField(default=0)
    build_location = models.CharField(max_length=200, blank=True)
    bom_revision = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    qty_produced = models.IntegerField(default=0)
    qty_passed = models.IntegerField(default=0)
    yield_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    customer_approval = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='pending')
    approval_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order']
        unique_together = ['project', 'name']

    def __str__(self):
        return f"{self.project.name} — {self.name}"

    def save(self, *args, **kwargs):
        if self.qty_produced > 0:
            self.yield_pct = round(self.qty_passed / self.qty_produced * 100, 2)
        else:
            self.yield_pct = 0
        super().save(*args, **kwargs)

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def approval_label(self):
        return dict(self.APPROVAL_CHOICES).get(self.customer_approval, self.customer_approval)

    @property
    def gate_readiness(self):
        tasks = self.tasks.all()
        total_tasks = tasks.count()
        done_tasks = tasks.filter(status='done').count()
        task_pct = round(done_tasks / total_tasks * 100) if total_tasks else 100

        nre_items = self.nre_items.all()
        total_nre = nre_items.count()
        nre_with_po = nre_items.exclude(po_status='no-po').count()
        nre_pct = round(nre_with_po / total_nre * 100) if total_nre else 100

        open_issues = self.issues.exclude(status='resolved').count()
        issue_pct = 0 if open_issues else 100

        auto_gates = [
            {'label': f'Tasks done: {done_tasks}/{total_tasks}', 'pct': task_pct, 'ok': task_pct == 100},
            {'label': f'NRE with PO: {nre_with_po}/{total_nre}', 'pct': nre_pct, 'ok': nre_pct == 100},
            {'label': f'Open issues: {open_issues}', 'pct': issue_pct, 'ok': open_issues == 0},
        ]
        auto_avg = sum(g['pct'] for g in auto_gates) / len(auto_gates)

        checklist = list(self.gate_items.all())
        manual_total = len(checklist)
        manual_checked = sum(1 for g in checklist if g.checked)
        manual_pct = round(manual_checked / manual_total * 100) if manual_total else 100

        overall = round((auto_avg + manual_pct) / 2) if manual_total else round(auto_avg)
        color = '#4ade80' if overall == 100 else '#fbbf24' if overall >= 50 else '#f87171'

        return {
            'auto_gates': auto_gates,
            'manual_items': checklist,
            'manual_checked': manual_checked,
            'manual_total': manual_total,
            'manual_pct': manual_pct,
            'overall_pct': overall,
            'color': color,
        }


class GateChecklistItem(models.Model):
    stage = models.ForeignKey(BuildStage, on_delete=models.CASCADE, related_name='gate_items')
    label = models.CharField(max_length=200)
    checked = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.label


class ProjectSection(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=200)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        unique_together = ['project', 'name']

    def __str__(self):
        return self.name


class Task(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'), ('inprogress', 'In Progress'),
        ('done', 'Done'), ('blocked', 'Blocked'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=300)
    section = models.ForeignKey(ProjectSection, on_delete=models.CASCADE, related_name='tasks')
    remark = models.TextField(blank=True)
    who = models.CharField(max_length=200, default='TBD')
    days = models.IntegerField(default=1)
    start = models.DateField()
    end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    stage = models.ForeignKey(BuildStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    sort_order = models.IntegerField(default=0)
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependents',
    )

    class Meta:
        ordering = ['section__sort_order', 'start']

    def save(self, *args, **kwargs):
        if self.start and self.end:
            self.days = (self.end - self.start).days + 1
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'days' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['days']
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def section_name(self):
        return self.section.name

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def stage_name(self):
        return self.stage.name if self.stage else ''

    @property
    def open_issues(self):
        return self.linked_issues.exclude(status='resolved')


class ProjectPlanVersion(models.Model):
    CHANGE_TYPE_CHOICES = [('major', 'Major'), ('minor', 'Minor')]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='plan_versions')
    version_major = models.PositiveIntegerField()
    version_minor = models.PositiveIntegerField()
    version_label = models.CharField(max_length=20)
    change_type = models.CharField(max_length=10, choices=CHANGE_TYPE_CHOICES, default='minor')
    change_comment = models.TextField()
    committed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='committed_versions',
    )
    committed_at = models.DateTimeField(auto_now_add=True)
    task_snapshot = models.JSONField()

    class Meta:
        ordering = ['-version_major', '-version_minor']
        unique_together = ['project', 'version_major', 'version_minor']

    def __str__(self):
        return f"{self.project.name} v{self.version_label}"

    @classmethod
    def next_version(cls, project, change_type):
        latest = cls.objects.filter(project=project).first()
        if not latest:
            return 1, 0
        if change_type == 'major':
            return latest.version_major + 1, 0
        return latest.version_major, latest.version_minor + 1

    @classmethod
    def snapshot_project(cls, project):
        tasks = project.tasks.select_related('section', 'stage').prefetch_related('depends_on').all()
        return [
            {
                'id': t.pk,
                'name': t.name,
                'section': t.section.name,
                'section_id': t.section_id,
                'remark': t.remark,
                'who': t.who,
                'days': t.days,
                'start': str(t.start),
                'end': str(t.end),
                'status': t.status,
                'stage': t.stage.name if t.stage else None,
                'stage_id': t.stage_id,
                'sort_order': t.sort_order,
                'depends_on': list(t.depends_on.values_list('id', flat=True)),
            }
            for t in tasks
        ]

    @property
    def diff_vs_previous(self):
        prev = ProjectPlanVersion.objects.filter(project=self.project).filter(
            models.Q(version_major__lt=self.version_major) |
            models.Q(version_major=self.version_major, version_minor__lt=self.version_minor)
        ).first()
        if not prev:
            return {'added': self.task_snapshot, 'removed': [], 'modified': [], 'is_initial': True}
        prev_by_id = {t['id']: t for t in prev.task_snapshot}
        curr_by_id = {t['id']: t for t in self.task_snapshot}
        added = [t for tid, t in curr_by_id.items() if tid not in prev_by_id]
        removed = [t for tid, t in prev_by_id.items() if tid not in curr_by_id]
        modified = []
        for tid, curr_t in curr_by_id.items():
            if tid in prev_by_id:
                prev_t = prev_by_id[tid]
                changes = {
                    k: {'from': prev_t.get(k), 'to': curr_t[k]}
                    for k in curr_t
                    if curr_t[k] != prev_t.get(k) and k != 'id'
                }
                if changes:
                    modified.append({'task': curr_t, 'changes': changes})
        return {'added': added, 'removed': removed, 'modified': modified, 'is_initial': False}


class Issue(models.Model):
    SEVERITY_CHOICES = [
        ('critical', 'Critical'), ('high', 'High'),
        ('medium', 'Medium'), ('low', 'Low'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'), ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
    ]
    SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    title = models.CharField(max_length=300)
    desc = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    owner = models.CharField(max_length=200, blank=True)
    due = models.DateField(null=True, blank=True)
    impact = models.CharField(max_length=500, blank=True)
    stage = models.ForeignKey(BuildStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='issues')
    linked_tasks = models.ManyToManyField(Task, blank=True, related_name='linked_issues')

    class Meta:
        ordering = ['status', 'severity']

    def __str__(self):
        return self.title

    @property
    def severity_label(self):
        return dict(self.SEVERITY_CHOICES).get(self.severity, self.severity)

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def stage_name(self):
        return self.stage.name if self.stage else ''


class TeamMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='team_members')
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=100, blank=True)
    company = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def initials(self):
        parts = self.name.split()
        return ''.join(p[0] for p in parts[:2]).upper()


class NREItem(models.Model):
    CATEGORY_CHOICES = [
        ('Stencil', 'Stencil'), ('Jig Fixture', 'Jig Fixture'),
        ('Test Fixture', 'Test Fixture'), ('Pallet', 'Pallet'),
        ('Programming Fixture', 'Programming Fixture'),
        ('Tooling', 'Tooling'), ('Other', 'Other'),
    ]
    PO_STATUS_CHOICES = [
        ('no-po', 'No PO'), ('po-requested', 'PO Requested'),
        ('po-received', 'PO Received'), ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='nre_items')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Stencil')
    desc = models.CharField(max_length=500)
    supplier = models.CharField(max_length=200, default='TBD')
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Project.CURRENCY_CHOICES, default='THB')
    po_status = models.CharField(max_length=20, choices=PO_STATUS_CHOICES, default='no-po')
    po_number = models.CharField(max_length=100, blank=True)
    due = models.DateField(null=True, blank=True)
    qty = models.IntegerField(default=1)
    notes = models.TextField(blank=True)
    stage = models.ForeignKey(BuildStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='nre_items')
    linked_tasks = models.ManyToManyField(Task, blank=True, related_name='linked_nre')

    class Meta:
        ordering = ['category', 'id']

    def __str__(self):
        return self.desc

    @property
    def total_cost(self):
        return self.cost * self.qty

    @property
    def is_overdue(self):
        return self.po_status == 'no-po' and self.due and self.due < date.today()

    @property
    def po_status_label(self):
        return dict(self.PO_STATUS_CHOICES).get(self.po_status, self.po_status)

    @property
    def currency_symbol(self):
        return {'THB': '฿', 'USD': '$', 'EUR': '€'}.get(self.currency, self.currency)

    @property
    def stage_name(self):
        return self.stage.name if self.stage else ''


class TaskTemplateSet(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SectionTemplate(models.Model):
    template_set = models.ForeignKey(
        TaskTemplateSet, on_delete=models.CASCADE, related_name='sections'
    )
    name = models.CharField(max_length=200)
    sort_order = models.IntegerField(default=0)
    depends_on = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dependent_sections',
        help_text='If set, this section starts after the selected section finishes.',
    )
    day_offset = models.IntegerField(
        default=0,
        help_text='Days from project start date. Ignored if depends_on is set.',
    )

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.template_set.name} / {self.name}'


class TaskTemplate(models.Model):
    section = models.ForeignKey(
        SectionTemplate, on_delete=models.CASCADE, related_name='tasks'
    )
    name = models.CharField(max_length=300)
    who = models.CharField(max_length=200, default='TBD')
    days = models.IntegerField(default=1)
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependents',
        help_text='Tasks that must finish before this task can start.',
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.section.name} / {self.name}'
