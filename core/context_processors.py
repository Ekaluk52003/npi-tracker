from .models import Project


def sidebar_context(request):
    if request.path.startswith('/admin/'):
        return {}
    return {
        'all_projects': Project.objects.all(),
    }
