from django.db import models
from datetime import date


class Project(models.Model):
    CURRENCY_CHOICES = [('THB', 'THB'), ('USD', 'USD'), ('EUR', 'EUR')]

    name = models.CharField(max_length=200)
    pgm = models.CharField(max_length=100, verbose_name='Program Manager')
    customer = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    color = models.CharField(max_length=7, default='#4f7ef8')
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
            return round((self.end_date - self.start_date).days / 30.4)
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
            ('etb', 'ETB', 'External Test Build', 1),
            ('ps', 'PS', 'Pre-Series Build', 2),
            ('fas', 'FAS', 'First Article Sample', 3),
        ]
        for stage_id, name, full_name, order in defaults:
            BuildStage.objects.get_or_create(
                project=self, stage_id=stage_id,
                defaults={'name': name, 'full_name': full_name, 'sort_order': order}
            )


class BuildStage(models.Model):
    STAGE_CHOICES = [('etb', 'ETB'), ('ps', 'PS'), ('fas', 'FAS')]
    STATUS_CHOICES = [
        ('planned', 'Planned'), ('ready', 'Ready'), ('in-progress', 'In Progress'),
        ('completed', 'Completed'), ('on-hold', 'On Hold'),
    ]
    APPROVAL_CHOICES = [
        ('pending', 'Pending'), ('approved', 'Approved'),
        ('conditional', 'Conditional'), ('rejected', 'Rejected'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='stages')
    stage_id = models.CharField(max_length=10, choices=STAGE_CHOICES)
    name = models.CharField(max_length=10)
    full_name = models.CharField(max_length=100)
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
        unique_together = ['project', 'stage_id']

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
        tasks = self.project.tasks.filter(stage=self.stage_id)
        total_tasks = tasks.count()
        done_tasks = tasks.filter(status='done').count()
        task_pct = round(done_tasks / total_tasks * 100) if total_tasks else 100

        nre_items = self.project.nre_items.filter(stage=self.stage_id)
        total_nre = nre_items.count()
        nre_with_po = nre_items.exclude(po_status='no-po').count()
        nre_pct = round(nre_with_po / total_nre * 100) if total_nre else 100

        open_issues = self.project.issues.filter(stage=self.stage_id).exclude(status='resolved').count()
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


class Task(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'), ('inprogress', 'In Progress'),
        ('done', 'Done'), ('blocked', 'Blocked'),
    ]
    STAGE_CHOICES = [('', '— None —'), ('etb', 'ETB'), ('ps', 'PS'), ('fas', 'FAS')]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=300)
    section = models.CharField(max_length=200, default='General')
    remark = models.TextField(blank=True)
    who = models.CharField(max_length=200, default='TBD')
    days = models.IntegerField(default=1)
    start = models.DateField()
    end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    stage = models.CharField(max_length=10, blank=True, default='', choices=STAGE_CHOICES)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'start']

    def __str__(self):
        return self.name

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def open_issues(self):
        return self.linked_issues.exclude(status='resolved')


class Issue(models.Model):
    SEVERITY_CHOICES = [
        ('critical', 'Critical'), ('high', 'High'),
        ('medium', 'Medium'), ('low', 'Low'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'), ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
    ]
    STAGE_CHOICES = [('', '— None —'), ('etb', 'ETB'), ('ps', 'PS'), ('fas', 'FAS')]
    SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    title = models.CharField(max_length=300)
    desc = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    owner = models.CharField(max_length=200, blank=True)
    due = models.DateField(null=True, blank=True)
    impact = models.CharField(max_length=500, blank=True)
    stage = models.CharField(max_length=10, blank=True, default='', choices=STAGE_CHOICES)
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
    STAGE_CHOICES = [('', '— None —'), ('etb', 'ETB'), ('ps', 'PS'), ('fas', 'FAS')]

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
    stage = models.CharField(max_length=10, blank=True, default='', choices=STAGE_CHOICES)
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
