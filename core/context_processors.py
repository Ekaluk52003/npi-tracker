from .models import Project


def sidebar_context(request):
    return {
        'all_projects': Project.objects.all(),
    }
