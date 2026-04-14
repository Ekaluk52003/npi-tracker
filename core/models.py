from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from datetime import date


class VisibilityChoices(models.TextChoices):
    ALL = 'all', 'All Users'
    INTERNAL = 'internal', 'Internal Only'
    CUSTOMER = 'customer', 'Customer Only'


class Customer(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Project(models.Model):
    CURRENCY_CHOICES = [('THB', 'THB'), ('USD', 'USD'), ('EUR', 'EUR')]

    name = models.CharField(max_length=200)
    product_code = models.CharField(max_length=100, blank=True, help_text='Product code or SKU')
    pgm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_projects',
        verbose_name='Program Manager'
    )
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='projects'
    )
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
        ordering = ['actual_date', 'planned_date']
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


class Milestone(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='milestones')
    name = models.CharField(max_length=200)
    sort_order = models.IntegerField(default=0)
    visibility = models.CharField(
        max_length=20,
        choices=VisibilityChoices.choices,
        default=VisibilityChoices.ALL,
        help_text='Controls who can see this milestone'
    )

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
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name='tasks')
    remark = models.TextField(blank=True)
    who = models.CharField(max_length=200, default='TBD')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_tasks',
    )
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
    visibility = models.CharField(
        max_length=20,
        choices=VisibilityChoices.choices,
        default=VisibilityChoices.ALL,
        help_text='Controls who can see this task'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subtasks',
        help_text='Parent task for work breakdown structure (max 2 levels recommended)'
    )
    is_summary = models.BooleanField(
        default=False,
        help_text='If true, this task aggregates progress from subtasks'
    )

    class Meta:
        ordering = ['milestone__sort_order', 'start']

    def clean(self):
        super().clean()
        # Prevent circular parent references
        if self.parent:
            if self.parent_id == self.pk:
                raise ValidationError({'parent': 'A task cannot be its own parent.'})
            # Check if parent is a descendant of this task (would create cycle)
            current = self.parent
            depth = 0
            max_depth = 10  # Safety limit
            while current and depth < max_depth:
                if current.pk == self.pk:
                    raise ValidationError({'parent': 'Cannot set parent: would create circular reference.'})
                current = current.parent
                depth += 1
            # Enforce max 2 levels (parent -> child, no grandchildren)
            if self.parent.parent_id is not None:
                raise ValidationError({'parent': 'Maximum nesting depth is 2 levels. Cannot set a subtask as parent.'})

    def save(self, *args, **kwargs):
        if self.start and self.end:
            self.days = (self.end - self.start).days + 1
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'days' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['days']
        # Auto-set is_summary if task has subtasks (only for saved instances)
        if not kwargs.get('force_is_summary') and self.pk:
            self.is_summary = self.subtasks.exists()
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

    @property
    def is_leaf_node(self):
        """True if this task has no subtasks (actual work unit)."""
        return not self.subtasks.exists()

    @property
    def progress_pct(self):
        """Progress percentage: 100 if done, roll-up from subtasks if summary."""
        if self.status == 'done':
            return 100
        if self.is_leaf_node:
            return 100 if self.status == 'done' else 0
        # Summary task: average of subtask progress
        subtasks = self.subtasks.all()
        if not subtasks:
            return 0
        total = sum(t.progress_pct for t in subtasks)
        return round(total / len(subtasks))

    @property
    def hierarchy_level(self):
        """Returns 0 (root), 1 (child), or 2+ (beyond limit)."""
        level = 0
        current = self.parent
        while current:
            level += 1
            current = current.parent
        return level

    @property
    def rollup_start(self):
        """For summary tasks, earliest subtask start. Own start if leaf."""
        if self.is_leaf_node:
            return self.start
        subtasks = self.subtasks.all()
        if not subtasks:
            return self.start
        return min(t.rollup_start for t in subtasks)

    @property
    def rollup_end(self):
        """For summary tasks, latest subtask end. Own end if leaf."""
        if self.is_leaf_node:
            return self.end
        subtasks = self.subtasks.all()
        if not subtasks:
            return self.end
        return max(t.rollup_end for t in subtasks)


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
        tasks = project.tasks.select_related('milestone', 'stage').prefetch_related('depends_on', 'subtasks').all()
        return [
            {
                'id': t.pk,
                'name': t.name,
                'section': t.milestone.name,
                'section_id': t.milestone_id,
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
                'parent_id': t.parent_id,
                'is_summary': t.is_summary,
                'progress_pct': t.progress_pct,
                'rollup_start': t.rollup_start.isoformat() if t.rollup_start else None,
                'rollup_end': t.rollup_end.isoformat() if t.rollup_end else None,
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
    CATEGORY_CHOICES = [
        ('design', 'Design'),
        ('quality', 'Quality'),
        ('supplier', 'Supplier'),
        ('process', 'Process'),
        ('test', 'Test'),
        ('other', 'Other'),
    ]
    SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    title = models.CharField(max_length=300)
    desc = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    owner = models.CharField(max_length=200, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reported_issues',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_issues',
    )
    due = models.DateField(null=True, blank=True)
    impact = models.CharField(max_length=500, blank=True)
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    stage = models.ForeignKey(BuildStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='issues')
    linked_tasks = models.ManyToManyField(Task, blank=True, related_name='linked_issues')
    visibility = models.CharField(
        max_length=20,
        choices=VisibilityChoices.choices,
        default=VisibilityChoices.ALL,
        help_text='Controls who can see this issue'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'severity']

    def save(self, *args, **kwargs):
        if self.pk:
            old = Issue.objects.filter(pk=self.pk).values_list('status', flat=True).first()
            if old != 'resolved' and self.status == 'resolved' and not self.resolved_at:
                from django.utils import timezone
                self.resolved_at = timezone.now()
            elif self.status != 'resolved':
                self.resolved_at = None
        super().save(*args, **kwargs)

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
    MEMBER_TYPE_CHOICES = [
        ('internal', 'Internal'),
        ('external', 'External'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='team_members')
    member_type = models.CharField(max_length=10, choices=MEMBER_TYPE_CHOICES, default='external')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='team_memberships'
    )
    name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=100, blank=True)
    company = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.member_type == 'internal' and self.user:
            return self.user.get_full_name() or self.user.username
        return self.name or 'Unnamed'

    @property
    def initials(self):
        parts = self.display_name.split()
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


class WebhookConfig(models.Model):
    EVENT_CHOICES = [
        ('issue_critical', 'Critical Issue Created'),
        ('issue_created', 'Any Issue Created'),
        ('issue_resolved', 'Issue Resolved'),
        ('stage_changed', 'Build Stage Status Changed'),
        ('task_blocked', 'Task Blocked'),
    ]

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2000, blank=True)
    event = models.CharField(max_length=50, choices=EVENT_CHOICES)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True,
        related_name='webhooks', help_text='Leave blank to receive events from all projects.'
    )
    recipient = models.EmailField(
        max_length=320, blank=True,
        help_text='Recipient email for chat webhooks. Leave blank for channel webhooks.',
    )
    is_active = models.BooleanField(default=True)
    # PA HTTP Webhook: PA auto-registers its callback URL via subscribe endpoint
    pa_token = models.CharField(
        max_length=64, blank=True,
        help_text='Secret token used in the subscribe URL to authenticate Power Automate.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_event_display()})'

    def generate_token(self):
        import secrets
        self.pa_token = secrets.token_urlsafe(32)

    def subscribe_path(self):
        return f'/webhooks/pa/subscribe/{self.pk}/{self.pa_token}/'


class InboundWebhook(models.Model):
    """Receives events FROM Power Automate (or any external system)."""
    ACTION_CHOICES = [
        ('create_issue', 'Create Issue'),
        ('update_task_status', 'Update Task Status'),
        ('update_stage_status', 'Update Build Stage Status'),
        ('create_task', 'Create Task'),
    ]

    name = models.CharField(max_length=200)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True,
        related_name='inbound_webhooks',
        help_text='Scope to a specific project. Leave blank to require project_id in the payload.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    call_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_action_display()})'

    def generate_token(self):
        import secrets
        self.token = secrets.token_urlsafe(32)

    @property
    def endpoint_path(self):
        return f'/api/inbound/{self.token}/'


class TaskTemplateSet(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class MilestoneTemplate(models.Model):
    template_set = models.ForeignKey(
        TaskTemplateSet, on_delete=models.CASCADE, related_name='milestones'
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
    milestone = models.ForeignKey(
        MilestoneTemplate, on_delete=models.CASCADE, related_name='tasks'
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
        return f'{self.milestone.name} / {self.name}'


class Role(models.Model):
    """Configurable role for permission system."""
    name = models.CharField(max_length=50, unique=True)
    key = models.SlugField(max_length=50, unique=True, help_text='Unique identifier used in code')
    description = models.TextField(blank=True)
    is_internal = models.BooleanField(default=True, help_text='Internal roles can see internal-only tasks/milestones/issues')
    is_superuser = models.BooleanField(default=False, help_text='Bypass all permission checks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    """Permission matrix defining what each role can do on each model."""
    ACTION_CHOICES = [
        ('view', 'View'),
        ('add', 'Create'),
        ('change', 'Edit'),
        ('delete', 'Delete'),
    ]

    MODEL_CHOICES = [
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
    ]

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    model_name = models.CharField(max_length=50, choices=MODEL_CHOICES)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)

    class Meta:
        unique_together = ['role', 'model_name', 'action']
        ordering = ['role', 'model_name', 'action']

    def __str__(self):
        return f'{self.role.name}: {self.model_name} - {self.action}'


class UserRoleAssignment(models.Model):
    """
    Assign roles to users.
    - If project is null: global role (applies to all projects)
    - If project is set: project-specific role
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='role_assignments'
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_assignments')
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='user_roles'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_roles',
        help_text='For customer-scoped access. If set, user can only view projects for this customer.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'role', 'project']
        ordering = ['user', 'role_id']

    def __str__(self):
        scope = 'Global' if self.project is None else self.project.name
        if self.customer:
            scope += f' [Customer: {self.customer.name}]'
        return f'{self.user.username}: {self.role.name} ({scope})'


class TaskDueDateChange(models.Model):
    """Tracks due date changes so assigned users are notified."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='due_date_changes')
    version = models.ForeignKey(ProjectPlanVersion, on_delete=models.CASCADE, related_name='date_changes')
    previous_end = models.DateField()
    new_end = models.DateField()
    detected_at = models.DateTimeField(auto_now_add=True)
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='acknowledged_date_changes',
    )

    class Meta:
        ordering = ['-detected_at']
        unique_together = ['task', 'version']

    def __str__(self):
        return f'{self.task.name}: {self.previous_end} → {self.new_end} (v{self.version.version_label})'

    @property
    def days_shifted(self):
        """Returns positive if extended, negative if shortened."""
        return (self.new_end - self.previous_end).days

    @property
    def shift_display(self):
        days = self.days_shifted
        if days > 0:
            return f'+{days} days'
        elif days < 0:
            return f'{days} days'
        return 'No change'
