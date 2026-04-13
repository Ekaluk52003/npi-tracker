from django import forms
from django.contrib.auth import get_user_model
from .models import Project, Milestone, Task, Issue, TeamMember, NREItem, BuildStage, GateChecklistItem, TaskTemplateSet, WebhookConfig, InboundWebhook, Customer

User = get_user_model()


input_cls = 'w-full bg-[var(--surface2)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)] focus:outline-none'
select_cls = input_cls
textarea_cls = input_cls + ' min-h-[60px] resize-y'


class ProjectMemberChoiceField(forms.ModelChoiceField):
    """Custom field to display team member name with their role."""

    def __init__(self, project=None, *args, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

    def label_from_instance(self, user):
        if self.project:
            # Get role from team member record
            team_member = self.project.team_members.filter(user=user, member_type='internal').first()
            if team_member and team_member.role:
                return f"{user.get_full_name() or user.username} ({team_member.role})"
        return user.get_full_name() or user.username


class ProjectForm(forms.ModelForm):
    pgm = forms.ModelChoiceField(
        queryset=User.objects.filter(
            role_assignments__role__key='pm',
            role_assignments__project__isnull=True
        ).distinct().order_by('first_name', 'last_name', 'username'),
        required=False,
        empty_label='— Select Program Manager —',
        widget=forms.Select(attrs={'class': select_cls})
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all().order_by('name'),
        required=False,
        empty_label='— Select Customer —',
        widget=forms.Select(attrs={'class': select_cls})
    )

    class Meta:
        model = Project
        fields = ['name', 'product_code', 'pgm', 'customer', 'start_date', 'end_date', 'color', 'annual_volume', 'annual_revenue', 'currency']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Greenland'}),
            'product_code': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PRD-001, SKU-12345'}),
            'start_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'color': forms.TextInput(attrs={'class': input_cls + ' h-10 w-full cursor-pointer', 'type': 'color'}),
            'annual_volume': forms.NumberInput(attrs={'class': input_cls, 'min': 0, 'placeholder': 'e.g. 100000'}),
            'annual_revenue': forms.NumberInput(attrs={'class': input_cls, 'min': 0, 'step': '0.01', 'placeholder': 'e.g. 5000000.00'}),
            'currency': forms.Select(attrs={'class': select_cls}),
        }


class TaskForm(forms.ModelForm):
    assigned_to = ProjectMemberChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='— Unassigned —',
    )

    class Meta:
        model = Task
        fields = ['name', 'milestone', 'remark', 'who', 'assigned_to', 'start', 'end', 'status', 'stage', 'visibility']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PCB Production'}),
            'milestone': forms.Select(attrs={'class': select_cls}),
            'remark': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'Supplier info, dependencies, notes…', 'rows': 2}),
            'who': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Axis, SVI'}),
            'start': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'end': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'status': forms.Select(attrs={'class': select_cls}),
            'stage': forms.Select(attrs={'class': select_cls}),
            'visibility': forms.Select(attrs={'class': select_cls}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['milestone'].queryset = project.milestones.all()
            self.fields['stage'].queryset = project.stages.all()
            # Filter assigned_to to project team members (internal users)
            internal_members = project.team_members.filter(member_type='internal', user__isnull=False)
            self.fields['assigned_to'].project = project
            self.fields['assigned_to'].queryset = User.objects.filter(
                pk__in=internal_members.values_list('user', flat=True)
            ).order_by('first_name', 'last_name', 'username')
        elif self.instance and self.instance.pk:
            self.fields['milestone'].queryset = self.instance.project.milestones.all()
            self.fields['stage'].queryset = self.instance.project.stages.all()
            # Filter assigned_to to project team members
            internal_members = self.instance.project.team_members.filter(member_type='internal', user__isnull=False)
            self.fields['assigned_to'].project = self.instance.project
            self.fields['assigned_to'].queryset = User.objects.filter(
                pk__in=internal_members.values_list('user', flat=True)
            ).order_by('first_name', 'last_name', 'username')
        self.fields['stage'].empty_label = '— None —'


class IssueForm(forms.ModelForm):
    assigned_to = ProjectMemberChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='— Unassigned —',
    )
    reported_by = ProjectMemberChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='— Unknown —',
    )

    class Meta:
        model = Issue
        fields = [
            'title', 'desc', 'category', 'severity', 'status',
            'owner', 'reported_by', 'assigned_to',
            'due', 'impact', 'resolution',
            'stage', 'linked_tasks', 'visibility',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Short description'}),
            'desc': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'What happened? Impact?', 'rows': 3}),
            'category': forms.Select(attrs={'class': select_cls}),
            'severity': forms.Select(attrs={'class': select_cls}),
            'status': forms.Select(attrs={'class': select_cls}),
            'owner': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Who is responsible?'}),
            'due': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'impact': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. ETB build delayed 2 weeks'}),
            'resolution': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'How was this resolved?', 'rows': 3}),
            'stage': forms.Select(attrs={'class': select_cls}),
            'linked_tasks': forms.CheckboxSelectMultiple(),
            'visibility': forms.Select(attrs={'class': select_cls}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['linked_tasks'].queryset = project.tasks.all()
            self.fields['stage'].queryset = project.stages.all()
            internal_members = project.team_members.filter(member_type='internal', user__isnull=False)
            member_qs = User.objects.filter(
                pk__in=internal_members.values_list('user', flat=True)
            ).order_by('first_name', 'last_name', 'username')
            self.fields['assigned_to'].project = project
            self.fields['assigned_to'].queryset = member_qs
            self.fields['reported_by'].project = project
            self.fields['reported_by'].queryset = member_qs
        elif self.instance and self.instance.pk:
            self.fields['stage'].queryset = self.instance.project.stages.all()
            internal_members = self.instance.project.team_members.filter(member_type='internal', user__isnull=False)
            member_qs = User.objects.filter(
                pk__in=internal_members.values_list('user', flat=True)
            ).order_by('first_name', 'last_name', 'username')
            self.fields['assigned_to'].project = self.instance.project
            self.fields['assigned_to'].queryset = member_qs
            self.fields['reported_by'].project = self.instance.project
            self.fields['reported_by'].queryset = member_qs
        self.fields['stage'].empty_label = '— None —'


class TeamMemberForm(forms.ModelForm):
    member_type = forms.ChoiceField(
        choices=TeamMember.MEMBER_TYPE_CHOICES,
        initial='external',
        widget=forms.Select(attrs={'class': select_cls, 'onchange': 'toggleMemberType(this)'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name', 'username'),
        required=False,
        empty_label='— Select User —',
        widget=forms.Select(attrs={'class': select_cls})
    )

    class Meta:
        model = TeamMember
        fields = ['member_type', 'user', 'name', 'role', 'company', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Full name'}),
            'role': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PGM, PCB Engineer'}),
            'company': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. SVI Thailand'}),
            'email': forms.EmailInput(attrs={'class': input_cls, 'placeholder': 'name@company.com'}),
            'phone': forms.TextInput(attrs={'class': input_cls, 'placeholder': '+66…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make name required only for external members
        self.fields['name'].required = False

    def clean(self):
        cleaned_data = super().clean()
        member_type = cleaned_data.get('member_type')
        user = cleaned_data.get('user')
        name = cleaned_data.get('name')

        if member_type == 'internal':
            if not user:
                self.add_error('user', 'Please select a user for internal members.')
            # Auto-populate name from user if not provided
            if user and not name:
                cleaned_data['name'] = user.get_full_name() or user.username
        else:
            # External member requires name
            if not name:
                self.add_error('name', 'Please enter a name for external members.')

        return cleaned_data


class NREItemForm(forms.ModelForm):
    class Meta:
        model = NREItem
        fields = ['category', 'desc', 'supplier', 'cost', 'currency', 'po_status', 'po_number', 'due', 'qty', 'stage', 'notes', 'linked_tasks']
        widgets = {
            'category': forms.Select(attrs={'class': select_cls}),
            'desc': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Top-side stencil for Main PCBA'}),
            'supplier': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. SVI, Local vendor'}),
            'cost': forms.NumberInput(attrs={'class': input_cls, 'min': 0, 'step': '0.01'}),
            'currency': forms.Select(attrs={'class': select_cls}),
            'po_status': forms.Select(attrs={'class': select_cls}),
            'po_number': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Customer PO #'}),
            'due': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'qty': forms.NumberInput(attrs={'class': input_cls, 'min': 1}),
            'stage': forms.Select(attrs={'class': select_cls}),
            'notes': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'Additional details…', 'rows': 2}),
            'linked_tasks': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['linked_tasks'].queryset = project.tasks.all()
            self.fields['stage'].queryset = project.stages.all()
        elif self.instance and self.instance.pk:
            self.fields['stage'].queryset = self.instance.project.stages.all()
        self.fields['stage'].empty_label = '— None —'


class BuildStageForm(forms.ModelForm):
    class Meta:
        model = BuildStage
        fields = [
            'name', 'full_name', 'color',
            'status', 'planned_date', 'actual_date', 'build_qty', 'build_location',
            'bom_revision', 'customer_approval', 'qty_produced', 'qty_passed',
            'approval_notes', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. EVT, DVT, PVT'}),
            'full_name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Engineering Verification Test'}),
            'color': forms.TextInput(attrs={'class': input_cls + ' h-10 w-full cursor-pointer', 'type': 'color'}),
            'status': forms.Select(attrs={'class': select_cls}),
            'planned_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'actual_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'build_qty': forms.NumberInput(attrs={'class': input_cls, 'min': 0}),
            'build_location': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. SVI Thailand'}),
            'bom_revision': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. R2.3'}),
            'customer_approval': forms.Select(attrs={'class': select_cls}),
            'qty_produced': forms.NumberInput(attrs={'class': input_cls, 'min': 0}),
            'qty_passed': forms.NumberInput(attrs={'class': input_cls, 'min': 0}),
            'approval_notes': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Minor rework on 2 units'}),
            'notes': forms.Textarea(attrs={'class': textarea_cls, 'rows': 2}),
        }


class GateChecklistItemForm(forms.ModelForm):
    class Meta:
        model = GateChecklistItem
        fields = ['label']
        widgets = {
            'label': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Add checklist item…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['label'].required = False


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ['name', 'sort_order', 'visibility']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Pre-req: Main PCBA'}),
            'sort_order': forms.NumberInput(attrs={'class': input_cls, 'min': 0}),
            'visibility': forms.Select(attrs={'class': select_cls}),
        }


class WebhookConfigForm(forms.ModelForm):
    class Meta:
        model = WebhookConfig
        fields = ['name', 'event', 'url', 'recipient', 'project', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Critical Issue → Teams'}),
            'event': forms.Select(attrs={'class': select_cls}),
            'url': forms.URLInput(attrs={'class': input_cls, 'placeholder': 'https://xxx.webhook.office.com/…'}),
            'recipient': forms.EmailInput(attrs={'class': input_cls, 'placeholder': 'user@company.com (blank = channel)'}),
            'project': forms.Select(attrs={'class': select_cls}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded border-[var(--border)] bg-[var(--surface2)] text-[var(--accent)]'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['url'].required = False
        self.fields['url'].label = 'Teams Incoming Webhook URL'
        self.fields['project'].empty_label = '— All projects —'
        self.fields['project'].required = False


class CommitForm(forms.Form):
    change_type = forms.ChoiceField(
        choices=[('minor', 'Minor'), ('major', 'Major')],
        initial='minor',
    )
    change_comment = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': textarea_cls,
            'placeholder': 'Describe what changed in this version…',
            'rows': 3,
        }),
    )


class InboundWebhookForm(forms.ModelForm):
    class Meta:
        model = InboundWebhook
        fields = ['name', 'action', 'project', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PA → Create Critical Issue'}),
            'action': forms.Select(attrs={'class': select_cls}),
            'project': forms.Select(attrs={'class': select_cls}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded border-[var(--border)] bg-[var(--surface2)] text-[var(--accent)]'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].empty_label = '— Require project_id in payload —'
        self.fields['project'].required = False

