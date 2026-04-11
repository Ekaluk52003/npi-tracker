from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Issue, BuildStage, Task


@receiver(pre_save, sender=Issue)
def _issue_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._prev_status = Issue.objects.get(pk=instance.pk).status
        except Issue.DoesNotExist:
            instance._prev_status = None
    else:
        instance._prev_status = None


@receiver(post_save, sender=Issue)
def _issue_post_save(sender, instance, created, **kwargs):
    from .webhooks import fire_event

    payload = {
        'event': '',
        'timestamp': timezone.now().isoformat(),
        'project': instance.project.name,
        'project_id': instance.project.pk,
        'customer': instance.project.customer,
        'pgm': instance.project.pgm,
        'issue_id': instance.pk,
        'issue_title': instance.title,
        'issue_severity': instance.severity,
        'issue_status': instance.status,
        'issue_owner': instance.owner,
        'issue_due': str(instance.due) if instance.due else '',
        'issue_impact': instance.impact,
        'issue_stage': instance.stage_name,
        'issue_desc': instance.desc,
    }

    if created:
        payload['event'] = 'issue_created'
        fire_event('issue_created', payload, project=instance.project)
        if instance.severity == 'critical':
            payload['event'] = 'issue_critical'
            fire_event('issue_critical', payload, project=instance.project)

    else:
        prev = getattr(instance, '_prev_status', None)
        if prev and prev != 'resolved' and instance.status == 'resolved':
            payload['event'] = 'issue_resolved'
            fire_event('issue_resolved', payload, project=instance.project)


@receiver(pre_save, sender=BuildStage)
def _stage_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._prev_status = BuildStage.objects.get(pk=instance.pk).status
        except BuildStage.DoesNotExist:
            instance._prev_status = None
    else:
        instance._prev_status = None


@receiver(post_save, sender=BuildStage)
def _stage_post_save(sender, instance, created, **kwargs):
    from .webhooks import fire_event

    if created:
        return

    prev = getattr(instance, '_prev_status', None)
    if prev is not None and prev != instance.status:
        payload = {
            'event': 'stage_changed',
            'timestamp': timezone.now().isoformat(),
            'project': instance.project.name,
            'project_id': instance.project.pk,
            'customer': instance.project.customer,
            'pgm': instance.project.pgm,
            'stage': instance.name,
            'stage_full_name': instance.full_name,
            'status_from': prev,
            'status_to': instance.status,
            'planned_date': str(instance.planned_date) if instance.planned_date else '',
            'actual_date': str(instance.actual_date) if instance.actual_date else '',
        }
        fire_event('stage_changed', payload, project=instance.project)


@receiver(pre_save, sender=Task)
def _task_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._prev_status = Task.objects.get(pk=instance.pk).status
        except Task.DoesNotExist:
            instance._prev_status = None
    else:
        instance._prev_status = None


@receiver(post_save, sender=Task)
def _task_post_save(sender, instance, created, **kwargs):
    from .webhooks import fire_event

    if created:
        return

    prev = getattr(instance, '_prev_status', None)
    if prev != 'blocked' and instance.status == 'blocked':
        payload = {
            'event': 'task_blocked',
            'timestamp': timezone.now().isoformat(),
            'project': instance.project.name,
            'project_id': instance.project.pk,
            'customer': instance.project.customer,
            'pgm': instance.project.pgm,
            'task_id': instance.pk,
            'task_name': instance.name,
            'task_who': instance.who,
            'task_start': str(instance.start),
            'task_end': str(instance.end),
            'task_stage': instance.stage_name,
            'task_section': instance.section_name,
        }
        fire_event('task_blocked', payload, project=instance.project)
