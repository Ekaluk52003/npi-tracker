from .models import Project, UserRoleAssignment
from .permissions import get_project_queryset, has_permission, can_view, can_add, can_change, can_delete


def sidebar_context(request):
    if request.path.startswith('/admin/'):
        return {}
    # Filter projects based on user role
    all_projects = Project.objects.all()
    if request.user.is_authenticated:
        all_projects = get_project_queryset(request.user, all_projects)
    return {
        'all_projects': all_projects,
    }


def user_permissions(request):
    """Expose user permissions to templates.

    Provides permission check functions and role information.
    """
    if not request.user.is_authenticated:
        return {}

    is_superuser = request.user.is_superuser

    # Helper functions for templates
    def _can_view(model_name, project=None):
        return is_superuser or can_view(request.user, model_name, project)

    def _can_add(model_name, project=None):
        return is_superuser or can_add(request.user, model_name, project)

    def _can_change(model_name, project=None):
        return is_superuser or can_change(request.user, model_name, project)

    def _can_delete(model_name, project=None):
        return is_superuser or can_delete(request.user, model_name, project)

    # Get primary role for display
    assignments = UserRoleAssignment.objects.filter(
        user=request.user, project__isnull=True
    ).select_related('role')
    primary_role = assignments.first().role if assignments.exists() else None

    return {
        'user_role': primary_role.key if primary_role else None,
        'user_role_name': primary_role.name if primary_role else None,
        'user_is_superuser': is_superuser,
        'can_view': _can_view,
        'can_add': _can_add,
        'can_change': _can_change,
        'can_delete': _can_delete,
    }
