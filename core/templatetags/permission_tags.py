"""Template tags for permission checking."""
from django import template
from core.permissions import can_view, can_add, can_change, can_delete

register = template.Library()


@register.simple_tag(takes_context=True)
def has_perm(context, model_name, action, project=None):
    """Check if user has permission for action on model.
    
    Usage: {% has_perm 'task' 'change' project as can_edit_task %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    
    if request.user.is_superuser:
        return True
    
    if action == 'view':
        return can_view(request.user, model_name, project)
    elif action == 'add':
        return can_add(request.user, model_name, project)
    elif action == 'change':
        return can_change(request.user, model_name, project)
    elif action == 'delete':
        return can_delete(request.user, model_name, project)
    return False


@register.simple_tag(takes_context=True)
def can_view_model(context, model_name, project=None):
    """Check if user can view the model.
    
    Usage: {% can_view_model 'task' project as can_view %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    return can_view(request.user, model_name, project)


@register.simple_tag(takes_context=True)
def can_add_model(context, model_name, project=None):
    """Check if user can add the model.
    
    Usage: {% can_add_model 'task' project as can_add %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    return can_add(request.user, model_name, project)


@register.simple_tag(takes_context=True)
def can_change_model(context, model_name, project=None):
    """Check if user can change the model.
    
    Usage: {% can_change_model 'task' project as can_change %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    return can_change(request.user, model_name, project)


@register.simple_tag(takes_context=True)
def can_delete_model(context, model_name, project=None):
    """Check if user can delete the model.
    
    Usage: {% can_delete_model 'task' project as can_delete %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    return can_delete(request.user, model_name, project)
