"""Access control and permission helpers for NPI Tracker."""

from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required


def get_role(user):
    """Return user's role string; defaults to 'engineer' if no profile exists."""
    if not user or not user.is_authenticated:
        return None
    try:
        return user.profile.role
    except Exception:
        # No UserProfile found; default to engineer
        return 'engineer'


def is_pm(user):
    """Check if user is a Project Manager."""
    return get_role(user) == 'pm'


def is_engineer(user):
    """Check if user is an Engineer."""
    return get_role(user) == 'engineer'


def is_customer(user):
    """Check if user is a Customer."""
    return get_role(user) == 'customer'


def get_project_queryset(user, base_qs):
    """Filter Project queryset based on user role.

    - Superusers see all projects
    - PM and Engineer see all projects
    - Customer users see only projects in their customer account
    """
    if user.is_superuser:
        return base_qs

    if is_customer(user):
        try:
            customer = user.profile.customer
        except Exception:
            customer = None

        if customer:
            return base_qs.filter(customer=customer)
        return base_qs.none()

    return base_qs


def can_view_project(user, project):
    """Check if user can view a specific project.

    - Superusers can view all projects
    - Customer users can only view their customer's projects
    - PM and Engineer can view all projects
    """
    if user.is_superuser:
        return True
    if is_customer(user):
        try:
            return user.profile.customer == project.customer
        except Exception:
            return False
    # PM and Engineer can view all projects
    return True


def can_edit_project(user):
    """Check if user can create/edit/delete projects.

    Only PM can, except superusers can do anything.
    """
    if user.is_superuser:
        return True
    return is_pm(user)


def can_edit_task(user, task=None):
    """Check if user can create/edit/delete tasks.

    Only PM can, except superusers can do anything.
    """
    if user.is_superuser:
        return True
    return is_pm(user)


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


def role_required(*roles):
    """View decorator to restrict access by role.

    Superusers bypass role checks.

    Usage:
        @role_required('pm')
        def my_view(request): ...

        @role_required('pm', 'engineer')
        def another_view(request): ...
    """
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
