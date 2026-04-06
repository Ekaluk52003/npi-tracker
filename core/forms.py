from django import forms
from .models import Project, ProjectSection, Task, Issue, TeamMember, NREItem, BuildStage, GateChecklistItem, TaskTemplateSet


input_cls = 'w-full bg-[var(--surface2)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)] focus:outline-none'
select_cls = input_cls
textarea_cls = input_cls + ' min-h-[60px] resize-y'


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'pgm', 'customer', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Greenland'}),
            'pgm': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Program Manager'}),
            'customer': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Axis'}),
            'start_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
        }


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['name', 'section', 'remark', 'who', 'days', 'start', 'end', 'status', 'stage']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PCB Production'}),
            'section': forms.Select(attrs={'class': select_cls}),
            'remark': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'Supplier info, dependencies, notes…', 'rows': 2}),
            'who': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Axis, SVI'}),
            'days': forms.NumberInput(attrs={'class': input_cls, 'min': 1}),
            'start': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'end': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'status': forms.Select(attrs={'class': select_cls}),
            'stage': forms.Select(attrs={'class': select_cls}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            self.fields['section'].queryset = project.sections.all()
            self.fields['stage'].queryset = project.stages.all()
        elif self.instance and self.instance.pk:
            self.fields['section'].queryset = self.instance.project.sections.all()
            self.fields['stage'].queryset = self.instance.project.stages.all()
        self.fields['stage'].empty_label = '— None —'


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['title', 'desc', 'severity', 'status', 'owner', 'due', 'impact', 'stage', 'linked_tasks']
        widgets = {
            'title': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Short description'}),
            'desc': forms.Textarea(attrs={'class': textarea_cls, 'placeholder': 'What happened? Impact?', 'rows': 3}),
            'severity': forms.Select(attrs={'class': select_cls}),
            'status': forms.Select(attrs={'class': select_cls}),
            'owner': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Who is responsible?'}),
            'due': forms.DateInput(attrs={'class': input_cls, 'type': 'date'}),
            'impact': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. ETB build delayed 2 weeks'}),
            'stage': forms.Select(attrs={'class': select_cls}),
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


class TeamMemberForm(forms.ModelForm):
    class Meta:
        model = TeamMember
        fields = ['name', 'role', 'company', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'Full name'}),
            'role': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. PGM, PCB Engineer'}),
            'company': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. SVI Thailand'}),
            'email': forms.EmailInput(attrs={'class': input_cls, 'placeholder': 'name@company.com'}),
            'phone': forms.TextInput(attrs={'class': input_cls, 'placeholder': '+66…'}),
        }


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
            'color': forms.TextInput(attrs={'class': input_cls, 'type': 'color'}),
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


class ProjectSectionForm(forms.ModelForm):
    class Meta:
        model = ProjectSection
        fields = ['name', 'sort_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': input_cls, 'placeholder': 'e.g. Pre-req: Main PCBA'}),
            'sort_order': forms.NumberInput(attrs={'class': input_cls, 'min': 0}),
        }

