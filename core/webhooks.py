import json
import threading
import requests
from django.utils import timezone


def _adaptive_card(payload):
    """Build a raw Adaptive Card dict — this IS the entire HTTP body for Workflows."""
    event = payload.get('event', '')
    project = payload.get('project', '')
    customer = payload.get('customer', '')
    pgm = payload.get('pgm', '')
    timestamp = payload.get('timestamp', '')[:19].replace('T', ' ')

    if event == 'issue_critical':
        heading = f'Critical Issue — {project}'
        facts = [
            ('Issue',    payload.get('issue_title', '')),
            ('Severity', 'Critical'),
            ('Project',  f'{project} ({customer})'),
            ('PGM',      pgm),
            ('Stage',    payload.get('issue_stage') or '—'),
            ('Owner',    payload.get('issue_owner') or '—'),
            ('Due',      payload.get('issue_due') or '—'),
            ('Impact',   payload.get('issue_impact') or '—'),
        ]
    elif event == 'issue_created':
        heading = f'New Issue — {project}'
        facts = [
            ('Issue',    payload.get('issue_title', '')),
            ('Severity', payload.get('issue_severity', '').capitalize()),
            ('Project',  f'{project} ({customer})'),
            ('PGM',      pgm),
            ('Stage',    payload.get('issue_stage') or '—'),
            ('Owner',    payload.get('issue_owner') or '—'),
            ('Due',      payload.get('issue_due') or '—'),
        ]
    elif event == 'issue_resolved':
        heading = f'Issue Resolved — {project}'
        facts = [
            ('Issue',   payload.get('issue_title', '')),
            ('Project', f'{project} ({customer})'),
            ('PGM',     pgm),
        ]
    elif event == 'stage_changed':
        heading = f'Stage Update — {project}'
        facts = [
            ('Stage',        payload.get('stage_full_name', payload.get('stage', ''))),
            ('Changed from', payload.get('status_from', '')),
            ('Changed to',   payload.get('status_to', '')),
            ('Project',      f'{project} ({customer})'),
            ('PGM',          pgm),
            ('Planned Date', payload.get('planned_date') or '—'),
        ]
    elif event == 'task_blocked':
        heading = f'Task Blocked — {project}'
        facts = [
            ('Task',        payload.get('task_name', '')),
            ('Project',     f'{project} ({customer})'),
            ('PGM',         pgm),
            ('Assigned to', payload.get('task_who') or '—'),
            ('Stage',       payload.get('task_stage') or '—'),
            ('End Date',    payload.get('task_end') or '—'),
        ]
    else:
        heading = f'NPI Tracker — {event}'
        facts = [
            ('Project', project),
            ('PGM',     pgm),
            ('Message', payload.get('message', '')),
        ]

    if payload.get('test'):
        heading = f'[Test] {heading}'

    facts.append(('Time', timestamp))

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": heading,
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": k, "value": str(v)}
                    for k, v in facts if v
                ],
            },
        ],
    }


def _deliver(config_id, payload, plain_text=False):
    from .models import WebhookConfig
    try:
        config = WebhookConfig.objects.get(pk=config_id)
        if not config.url:
            return

        if plain_text:
            # Minimal Adaptive Card for debugging
            body = {
                "type": "AdaptiveCard",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "NPI Tracker — connection OK",
                        "weight": "Bolder",
                        "wrap": True,
                    }
                ],
            }
        else:
            body = _adaptive_card(payload)

        # Wrap card with recipient for chat webhooks; bare card for channels
        recipient = getattr(config, 'recipient', '') or ''
        if recipient:
            http_body = {
                "recipient": recipient,
                "card": body,
            }
        else:
            http_body = body

        resp = requests.post(
            config.url,
            json=http_body,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        config.last_triggered_at = timezone.now()
        config.last_error = ''
        config.save(update_fields=['last_triggered_at', 'last_error'])
    except Exception as exc:
        try:
            config = WebhookConfig.objects.get(pk=config_id)
            config.last_error = str(exc)[:500]
            config.save(update_fields=['last_error'])
        except Exception:
            pass


def fire_event(event, payload, project=None):
    from django.db.models import Q
    from .models import WebhookConfig

    qs = WebhookConfig.objects.filter(event=event, is_active=True).exclude(url='')
    if project is not None:
        qs = qs.filter(Q(project=project) | Q(project__isnull=True))

    for config in qs:
        t = threading.Thread(target=_deliver, args=(config.pk, payload), daemon=True)
        t.start()
