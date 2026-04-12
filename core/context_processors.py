from .models import Project
from .permissions import get_role, get_project_queryset


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
    """Expose user role information to templates.

    Superusers are treated as PMs for all template purposes.
    """
    if not request.user.is_authenticated:
        return {}
    role = get_role(request.user)
    is_superuser = request.user.is_superuser
    return {
        'user_role': role,
        'user_is_pm': is_superuser or role == 'pm',
        'user_is_engineer': is_superuser or role == 'engineer',
        'user_is_customer': role == 'customer',  # Never treat superuser as customer
    }
