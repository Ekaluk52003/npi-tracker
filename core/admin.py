from django.contrib import admin
from .models import (
    Project, BuildStage, GateChecklistItem, ProjectSection, Task, Issue, TeamMember, NREItem,
    TaskTemplateSet, SectionTemplate, TaskTemplate,
)


class BuildStageInline(admin.TabularInline):
    model = BuildStage
    extra = 0


class ProjectSectionInline(admin.TabularInline):
    model = ProjectSection
    extra = 0


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0


class IssueInline(admin.TabularInline):
    model = Issue
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'customer', 'pgm', 'start_date', 'end_date']
    inlines = [BuildStageInline, ProjectSectionInline, TaskInline, IssueInline]


@admin.register(BuildStage)
class BuildStageAdmin(admin.ModelAdmin):
    list_display = ['project', 'name', 'full_name', 'status', 'color', 'planned_date']
    list_filter = ['status']


@admin.register(GateChecklistItem)
class GateChecklistItemAdmin(admin.ModelAdmin):
    list_display = ['label', 'stage', 'checked']


@admin.register(ProjectSection)
class ProjectSectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'sort_order']
    list_filter = ['project']
    list_editable = ['sort_order']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'section', 'status', 'stage', 'start', 'end']
    list_filter = ['status']


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'severity', 'status', 'stage']
    list_filter = ['severity', 'status']


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'role', 'company']


@admin.register(NREItem)
class NREItemAdmin(admin.ModelAdmin):
    list_display = ['desc', 'project', 'category', 'cost', 'po_status', 'stage']
    list_filter = ['category', 'po_status']


class SectionTemplateInline(admin.TabularInline):
    model = SectionTemplate
    extra = 1
    fields = ['sort_order', 'name', 'depends_on', 'day_offset']


class TaskTemplateInline(admin.TabularInline):
    model = TaskTemplate
    extra = 1
    fields = ['sort_order', 'name', 'who', 'days']


@admin.register(TaskTemplateSet)
class TaskTemplateSetAdmin(admin.ModelAdmin):
    list_display = ['name', 'section_count', 'created_at']
    inlines = [SectionTemplateInline]

    @admin.display(description='Sections')
    def section_count(self, obj):
        return obj.sections.count()


@admin.register(SectionTemplate)
class SectionTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'template_set', 'sort_order', 'depends_on', 'day_offset', 'task_count']
    list_filter = ['template_set']
    list_editable = ['sort_order', 'depends_on', 'day_offset']
    inlines = [TaskTemplateInline]

    @admin.display(description='Tasks')
    def task_count(self, obj):
        return obj.tasks.count()


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'section', 'days', 'sort_order']
    list_filter = ['section__template_set']
    list_editable = ['sort_order']
    filter_horizontal = ['depends_on']
    search_fields = ['name', 'section__name']
    ordering = ['section__template_set', 'section__sort_order', 'sort_order', 'id']
