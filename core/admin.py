from django.contrib import admin
import nested_admin
from .models import (
    Project, BuildStage, GateChecklistItem, Milestone, Task, Issue, TeamMember, NREItem,
    TaskTemplateSet, MilestoneTemplate, TaskTemplate, ProjectPlanVersion, InboundWebhook,
    Customer, Role, RolePermission, UserRoleAssignment,
)


class BuildStageInline(admin.TabularInline):
    model = BuildStage
    extra = 0


class MilestoneInline(admin.TabularInline):
    model = Milestone
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
    inlines = [BuildStageInline, MilestoneInline, TaskInline, IssueInline]


@admin.register(BuildStage)
class BuildStageAdmin(admin.ModelAdmin):
    list_display = ['project', 'name', 'full_name', 'status', 'color', 'planned_date']
    list_filter = ['status']


@admin.register(GateChecklistItem)
class GateChecklistItemAdmin(admin.ModelAdmin):
    list_display = ['label', 'stage', 'checked']


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'sort_order']
    list_filter = ['project']
    list_editable = ['sort_order']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'milestone', 'status', 'stage', 'start', 'end']
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


class TaskTemplateNestedInline(nested_admin.NestedTabularInline):
    model = TaskTemplate
    extra = 0
    fields = ['sort_order', 'name', 'who', 'days']
    sortable_field_name = 'sort_order'


class MilestoneTemplateNestedInline(nested_admin.NestedStackedInline):
    model = MilestoneTemplate
    extra = 0
    fields = ['sort_order', 'name', 'depends_on', 'day_offset']
    inlines = [TaskTemplateNestedInline]
    sortable_field_name = 'sort_order'


# Keep flat inlines for standalone MilestoneTemplate admin
class TaskTemplateInline(admin.TabularInline):
    model = TaskTemplate
    extra = 0
    fields = ['sort_order', 'name', 'who', 'days']


@admin.register(TaskTemplateSet)
class TaskTemplateSetAdmin(nested_admin.NestedModelAdmin):
    list_display = ['name', 'section_count', 'created_at']
    inlines = [MilestoneTemplateNestedInline]

    class Media:
        js = (
            'admin/js/vendor/jquery/jquery.min.js',
            'admin/js/jquery.init.js',
            'core/admin/inline_collapse.js',
        )

    @admin.display(description='Sections')
    def section_count(self, obj):
        return obj.sections.count()


@admin.register(MilestoneTemplate)
class MilestoneTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'template_set', 'sort_order', 'depends_on', 'day_offset', 'task_count']
    list_filter = ['template_set']
    list_editable = ['sort_order', 'depends_on', 'day_offset']
    inlines = [TaskTemplateInline]

    @admin.display(description='Tasks')
    def task_count(self, obj):
        return obj.tasks.count()


@admin.register(ProjectPlanVersion)
class ProjectPlanVersionAdmin(admin.ModelAdmin):
    list_display = ['project', 'version_label', 'change_type', 'committed_by', 'committed_at']
    list_filter = ['project', 'change_type']
    readonly_fields = ['task_snapshot', 'committed_at']


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'milestone', 'days', 'sort_order']
    list_filter = ['milestone__template_set']
    list_editable = ['sort_order']
    filter_horizontal = ['depends_on']
    search_fields = ['name', 'milestone__name']
    ordering = ['milestone__template_set', 'milestone__sort_order', 'sort_order', 'id']


@admin.register(InboundWebhook)
class InboundWebhookAdmin(admin.ModelAdmin):
    list_display = ['name', 'action', 'project', 'is_active', 'call_count', 'last_received_at']
    list_filter = ['action', 'is_active']
    readonly_fields = ['token', 'call_count', 'last_received_at', 'last_error']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    fields = ['model_name', 'action']


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'key', 'is_internal', 'is_superuser', 'created_at']
    list_filter = ['is_internal', 'is_superuser']
    search_fields = ['name', 'key', 'description']
    inlines = [RolePermissionInline]
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        (None, {'fields': ('name', 'key', 'description')}),
        ('Status', {'fields': ('is_internal', 'is_superuser')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ['role', 'model_name', 'action']
    list_filter = ['role', 'model_name', 'action']
    search_fields = ['role__name']


@admin.register(UserRoleAssignment)
class UserRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'project', 'customer', 'created_at']
    list_filter = ['role', 'project', 'customer']
    search_fields = ['user__username', 'user__email', 'role__name']
    raw_id_fields = ['user', 'project', 'customer']
    date_hierarchy = 'created_at'
