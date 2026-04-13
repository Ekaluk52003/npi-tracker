"""Access control and permission helpers for NPI Tracker."""

import warnings
from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q


def has_permission(user, model_name, action, project=None):
    """
    Check if user has permission to perform action on model.
    
    Args:
        user: Django User instance
        model_name: str - e.g., 'project', 'task', 'issue'
        action: str - 'view', 'add', 'change', 'delete'
        project: Optional[Project] - for project-scoped checks
        
    Returns:
        bool: True if user has permission
    """
    if not user or not user.is_authenticated:
        return False
    
    # Superusers always have permission
    if user.is_superuser:
        return True
    
    try:
        from .models import RolePermission, UserRoleAssignment, Role
        
        # Get user's role assignments
        if project:
            # Check project-specific role first, then global role
            assignments = UserRoleAssignment.objects.filter(
                user=user
            ).filter(
                Q(project=project) | Q(project__isnull=True)
            ).select_related('role')
        else:
            # Only global roles apply
            assignments = UserRoleAssignment.objects.filter(
                user=user, project__isnull=True
            ).select_related('role')
        
        for assignment in assignments:
            role = assignment.role
            
            # Superuser roles bypass all checks
            if role.is_superuser:
                return True
            
            # Check if role has this permission
            if RolePermission.objects.filter(
                role=role,
                model_name=model_name,
                action=action
            ).exists():
                return True
        
        return False
        
    except ObjectDoesNotExist:
        return False
    except Exception:
        # Fallback to legacy role system for backward compatibility
        return _legacy_has_permission(user, model_name, action)


def _legacy_has_permission(user, model_name, action):
    """Fallback to legacy role system during migration."""
    role = get_role(user)
    
    # PM can do everything
    if role == 'pm':
        return True
    
    # Engineers can view everything, edit issues assigned to them
    if role == 'engineer':
        if action == 'view':
            return True
        return False
    
    # Customers can only view their own projects
    if role == 'customer':
        if action == 'view' and model_name in ['project', 'task', 'issue']:
            return True
        return False
    
    return False


def permission_required(model_name, action, project_param=None, project_from_instance=False):
    """
    View decorator to restrict access by permission.
    
    Args:
        model_name: str - e.g., 'project', 'task', 'issue'
        action: str - 'view', 'add', 'change', 'delete'
        project_param: Optional[str] - URL parameter name containing project_id (e.g., 'pk')
        project_from_instance: bool - If True, extract project from instance in kwargs
        
    Usage:
        @permission_required('project', 'change')
        def project_create(request): ...
        
        @permission_required('task', 'change', project_param='pk')
        def task_edit(request, pk, tid): ...
        
        @permission_required('issue', 'delete', project_param='pk')
        def issue_delete(request, pk, iid): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            user = request.user
            
            # Superusers bypass permission checks
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            project = None
            
            # Get project from URL parameter if specified
            if project_param and project_param in kwargs:
                try:
                    from .models import Project
                    project_id = kwargs.get(project_param)
                    if project_id:
                        project = Project.objects.get(pk=project_id)
                except ObjectDoesNotExist:
                    return HttpResponseForbidden("Project not found.")
            
            if has_permission(user, model_name, action, project):
                return view_func(request, *args, **kwargs)
            
            return HttpResponseForbidden(
                "You don't have permission to perform this action."
            )
        return wrapper
    return decorator


def can_view(user, model_name, project=None):
    """Shorthand for view permission check."""
    return has_permission(user, model_name, 'view', project)


def can_add(user, model_name, project=None):
    """Shorthand for add/create permission check."""
    return has_permission(user, model_name, 'add', project)


def can_change(user, model_name, project=None):
    """Shorthand for edit permission check."""
    return has_permission(user, model_name, 'change', project)


def can_delete(user, model_name, project=None):
    """Shorthand for delete permission check."""
    return has_permission(user, model_name, 'delete', project)


def get_role(user):
    """Return user's primary role string from UserRoleAssignment.

    .. deprecated::
        This function is deprecated. Use `has_permission()` instead.
    """
    if not user or not user.is_authenticated:
        return None
    from .models import UserRoleAssignment
    try:
        assignment = UserRoleAssignment.objects.filter(
            user=user, project__isnull=True
        ).select_related('role').first()
        if assignment:
            return assignment.role.key
    except Exception:
        pass
    return 'engineer'  # Default fallback


def _get_user_customer(user):
    """Get customer from user's role assignment for customer-scoped access."""
    from .models import UserRoleAssignment
    try:
        assignment = UserRoleAssignment.objects.filter(
            user=user, customer__isnull=False
        ).select_related('customer').first()
        if assignment:
            return assignment.customer
    except Exception:
        pass
    return None


def is_customer_role(user):
    """Check if user has a customer role assignment (for project filtering)."""
    from .models import UserRoleAssignment
    try:
        return UserRoleAssignment.objects.filter(
            user=user, customer__isnull=False
        ).exists()
    except Exception:
        return False


def get_project_queryset(user, base_qs):
    """Filter Project queryset based on user role assignments.

    - Superusers see all projects
    - Users with customer-scoped roles see only their customer's projects
    - Other users see all projects they have any permission for
    """
    if user.is_superuser:
        return base_qs

    # Check for customer-scoped access
    customer = _get_user_customer(user)
    if customer:
        return base_qs.filter(customer=customer)

    return base_qs


def can_view_project(user, project):
    """Check if user can view a specific project.

    - Superusers can view all projects
    - Users with customer-scoped roles can only view their customer's projects
    - Other users with any project permission can view all projects
    """
    if user.is_superuser:
        return True

    # Check for customer-scoped access
    customer = _get_user_customer(user)
    if customer:
        return customer == project.customer

    # Check if user has any permission for projects
    return has_permission(user, 'project', 'view')


def can_edit_project(user):
    """Check if user can create/edit/delete projects.

    Uses new permission system.
    """
    return has_permission(user, 'project', 'change')


def can_edit_task(user, task=None):
    """Check if user can create/edit/delete tasks.

    Uses new permission system.
    """
    return has_permission(user, 'task', 'change')


def can_edit_issue(user, issue):
    """Check if user can edit an issue.

    - PM can edit all issues
    - Engineer can only edit issues assigned to them
    - Customer cannot edit issues
    - Superusers can do anything
    """
    if user.is_superuser:
        return True
    if is_pm(user):
        return True
    if is_engineer(user):
        return issue.assigned_to_id == user.id
    return False


def can_create_issue(user):
    """Check if user can create issues.

    Only PM can, except superusers can do anything.
    """
    if user.is_superuser:
        return True
    return is_pm(user)


def is_internal_user(user):
    """Check if user has any internal role.
    
    Uses Role.is_internal flag - configurable via admin.
    """
    from .models import UserRoleAssignment
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return UserRoleAssignment.objects.filter(
        user=user,
        role__is_internal=True
    ).exists()


def filter_visible_items(queryset, user):
    """Filter queryset based on user role and item visibility.
    
    Usage:
        tasks = filter_visible_items(project.tasks.all(), request.user)
        issues = filter_visible_items(project.issues.all(), request.user)
        milestones = filter_visible_items(project.milestones.all(), request.user)
    
    Visibility rules:
    - 'all': Everyone can see
    - 'internal': Only internal users (pm, engineer, admin, superuser)
    - 'customer': Internal users + customer users see this
    """
    if not user or not user.is_authenticated:
        # Anonymous users see nothing
        return queryset.none()
    
    if user.is_superuser:
        # Superusers see everything
        return queryset
    
    if is_internal_user(user):
        # Internal users see 'all' and 'internal' items
        # They don't see 'customer-only' items (those are for external customer users)
        return queryset.filter(visibility__in=['all', 'internal'])
    else:
        # External/customer users see 'all' and 'customer' items
        return queryset.filter(visibility__in=['all', 'customer'])


def role_required(*roles):
    """View decorator to restrict access by role.

    .. deprecated::
        Use `permission_required(model, action, project_param)` instead.
        This decorator is deprecated and will be removed in a future version.

    Superusers bypass role checks.

    Usage:
        @role_required('pm')
        def my_view(request): ...

        @role_required('pm', 'engineer')
        def another_view(request): ...
    """
    warnings.warn(
        "@role_required() is deprecated. Use @permission_required() instead. "
        "See permissions.py for new decorator usage.",
        DeprecationWarning,
        stacklevel=2
    )

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            # Superusers bypass role checks
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            user_role = get_role(request.user)
            if user_role not in roles:
                return HttpResponseForbidden(
                    "You don't have permission to perform this action."
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
