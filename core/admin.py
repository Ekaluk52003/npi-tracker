from django.contrib import admin
from .models import Project, BuildStage, GateChecklistItem, Task, Issue, TeamMember, NREItem


class BuildStageInline(admin.TabularInline):
    model = BuildStage
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
    inlines = [BuildStageInline, TaskInline, IssueInline]


@admin.register(BuildStage)
class BuildStageAdmin(admin.ModelAdmin):
    list_display = ['project', 'name', 'status', 'planned_date']
    list_filter = ['status', 'stage_id']


@admin.register(GateChecklistItem)
class GateChecklistItemAdmin(admin.ModelAdmin):
    list_display = ['label', 'stage', 'checked']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'section', 'status', 'start', 'end']
    list_filter = ['status', 'stage']


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'severity', 'status']
    list_filter = ['severity', 'status']


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'role', 'company']


@admin.register(NREItem)
class NREItemAdmin(admin.ModelAdmin):
    list_display = ['desc', 'project', 'category', 'cost', 'po_status']
    list_filter = ['category', 'po_status']
