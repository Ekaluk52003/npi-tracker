"""Template tags for permission checking."""
import json
from django import template
from django.utils.safestring import mark_safe
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


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key.
    
    Usage: {{ my_dict|get_item:my_key }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def subtract_date(date1, date2):
    """Subtract two dates and return days difference.
    
    Usage: {{ date1|subtract_date:date2 }}
    """
    if date1 is None or date2 is None:
        return 0
    return (date1 - date2).days


@register.filter
def div(numerator, denominator):
    """Divide two numbers.
    
    Usage: {{ value|div:100 }}
    """
    try:
        if denominator == 0:
            return 0
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return 0


@register.filter
def multiply(value, multiplier):
    """Multiply two numbers.
    
    Usage: {{ value|multiply:100 }}
    """
    try:
        return value * multiplier
    except TypeError:
        return 0


@register.filter
def json_safe(value):
    """Serialize value to JSON for safe use in JavaScript.
    
    Usage: {{ my_data|json_safe }}
    """
    if value is None:
        return mark_safe('null')
    try:
        return mark_safe(json.dumps(value))
    except (TypeError, ValueError):
        return mark_safe('null')
