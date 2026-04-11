"""
Inbound webhook handlers — processes JSON payloads from Power Automate
and performs the configured action in NPI Tracker.

Supports two methods:
  POST /api/inbound/<token>/   — JSON body (requires Premium HTTP connector)
  GET  /api/inbound/<token>/   — query-param payload (free via OneDrive "Upload file from URL")
"""
import json
import logging
from datetime import date
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import InboundWebhook, Project, Task, BuildStage, Issue, ProjectSection

logger = logging.getLogger(__name__)


@csrf_exempt
def inbound_webhook_receive(request, token):
    """
    Public endpoint: POST or GET /api/inbound/<token>/

    POST — Accepts JSON body from Power Automate HTTP action (Premium).
    GET  — Reads query parameters; used by OneDrive "Create file from URL" trick (Free).
           Example: /api/inbound/<token>/?title=Bug&severity=critical&project_id=1
    """
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        webhook = InboundWebhook.objects.select_related('project').get(token=token)
    except InboundWebhook.DoesNotExist:
        return JsonResponse({'error': 'Invalid token'}, status=403)

    if not webhook.is_active:
        return JsonResponse({'error': 'Webhook is disabled'}, status=403)

    # Extract payload from body (POST) or query params (GET)
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            _record_error(webhook, 'Invalid JSON body')
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    else:
        # GET — build payload from query parameters
        payload = {k: v for k, v in request.GET.items()}

    # Resolve project from webhook config or payload
    project = webhook.project
    if not project:
        project = _resolve_project(payload)
        if not project:
            _record_error(webhook, 'project_id or project_name required when webhook has no default project')
            return JsonResponse({'error': 'project_id or project_name is required in payload'}, status=400)

    # Dispatch to handler
    handler = _HANDLERS.get(webhook.action)
    if not handler:
        _record_error(webhook, f'Unknown action: {webhook.action}')
        return JsonResponse({'error': f'Unknown action: {webhook.action}'}, status=400)

    try:
        result = handler(project, payload)
    except Exception as exc:
        _record_error(webhook, str(exc)[:500])
        return JsonResponse({'error': str(exc)}, status=400)

    # Success — update stats
    webhook.last_received_at = timezone.now()
    webhook.last_error = ''
    webhook.call_count = (webhook.call_count or 0) + 1
    webhook.save(update_fields=['last_received_at', 'last_error', 'call_count'])

    return JsonResponse({'status': 'ok', **result}, status=200)


# ── Action handlers ──────────────────────────────────────────────────────


def _handle_create_issue(project, payload):
    """
    Expected payload:
    {
        "title": "Component shortage",
        "severity": "critical",        # critical | high | medium | low
        "status": "open",              # open | investigating | resolved  (optional)
        "owner": "John Doe",           # optional
        "due": "2025-06-01",           # optional, ISO date
        "impact": "ETB delayed 2 wk",  # optional
        "desc": "...",                  # optional
        "stage": "ETB"                 # optional, stage name
    }

    If "raw_text" is provided (e.g. email body) and no "title", uses Gemini LLM
    to parse the free-text into structured fields automatically.
    """
    # If raw_text present and no title, parse with LLM
    if payload.get('raw_text') and not payload.get('title', '').strip():
        parsed = _parse_email_with_llm(payload['raw_text'], project)
        # Merge parsed fields into payload (don't overwrite explicit values)
        for key, val in parsed.items():
            if key not in payload or not payload[key]:
                payload[key] = val

    title = payload.get('title', '').strip()
    if not title:
        raise ValueError('title is required (provide title directly or raw_text for LLM parsing)')

    severity = payload.get('severity', 'medium').lower()
    if severity not in ('critical', 'high', 'medium', 'low'):
        raise ValueError(f'Invalid severity: {severity}')

    status = payload.get('status', 'open').lower()
    if status not in ('open', 'investigating', 'resolved'):
        status = 'open'

    stage = _resolve_stage(project, payload.get('stage'))
    due = _parse_date(payload.get('due'))

    issue = Issue.objects.create(
        project=project,
        title=title,
        desc=payload.get('desc', ''),
        severity=severity,
        status=status,
        owner=payload.get('owner', ''),
        due=due,
        impact=payload.get('impact', ''),
        stage=stage,
    )
    return {'issue_id': issue.pk, 'action': 'create_issue'}


def _handle_update_task_status(project, payload):
    """
    Expected payload:
    {
        "task_id": 42,                 # or "task_name": "PCB Production"
        "status": "done"               # open | inprogress | done | blocked
    }
    """
    task = _resolve_task(project, payload)
    new_status = payload.get('status', '').lower()
    valid = ('open', 'inprogress', 'done', 'blocked')
    if new_status not in valid:
        raise ValueError(f'Invalid status: {new_status}. Must be one of {valid}')

    task.status = new_status
    task.save(update_fields=['status'])
    return {'task_id': task.pk, 'action': 'update_task_status', 'new_status': new_status}


def _handle_update_stage_status(project, payload):
    """
    Expected payload:
    {
        "stage_id": 5,                 # or "stage_name": "ETB"
        "status": "in-progress"        # planned | ready | in-progress | completed | on-hold
    }
    """
    stage = _resolve_stage_required(project, payload)
    new_status = payload.get('status', '').lower()
    valid = ('planned', 'ready', 'in-progress', 'completed', 'on-hold')
    if new_status not in valid:
        raise ValueError(f'Invalid status: {new_status}. Must be one of {valid}')

    stage.status = new_status
    stage.save(update_fields=['status'])
    return {'stage_id': stage.pk, 'action': 'update_stage_status', 'new_status': new_status}


def _handle_create_task(project, payload):
    """
    Expected payload:
    {
        "name": "Order stencils",
        "section": "Pre-req: Main PCBA",   # section name, created if missing
        "who": "SVI",                       # optional, defaults to TBD
        "start": "2025-05-01",              # ISO date
        "end": "2025-05-07",                # ISO date
        "status": "open",                   # optional
        "stage": "ETB",                     # optional, stage name
        "remark": "..."                     # optional
    }
    """
    name = payload.get('name', '').strip()
    if not name:
        raise ValueError('name is required')

    start = _parse_date(payload.get('start'))
    end = _parse_date(payload.get('end'))
    if not start or not end:
        raise ValueError('start and end dates are required (ISO format)')

    section_name = payload.get('section', '').strip()
    if not section_name:
        raise ValueError('section name is required')

    section, _ = ProjectSection.objects.get_or_create(
        project=project, name=section_name,
        defaults={'sort_order': project.sections.count()},
    )

    status = payload.get('status', 'open').lower()
    if status not in ('open', 'inprogress', 'done', 'blocked'):
        status = 'open'

    stage = _resolve_stage(project, payload.get('stage'))

    task = Task.objects.create(
        project=project,
        name=name,
        section=section,
        who=payload.get('who', 'TBD'),
        start=start,
        end=end,
        status=status,
        stage=stage,
        remark=payload.get('remark', ''),
        sort_order=project.tasks.count(),
    )
    return {'task_id': task.pk, 'action': 'create_task'}


# ── Helpers ──────────────────────────────────────────────────────────────


def _resolve_project(payload):
    """Resolve project by project_id or project_name (case-insensitive).
    Returns None if neither is provided or project not found."""
    # Try project_id first
    project_id = payload.get('project_id')
    if project_id:
        try:
            return Project.objects.get(pk=int(project_id))
        except (Project.DoesNotExist, ValueError, TypeError):
            return None

    # Try project_name (exact case-insensitive, then partial match)
    project_name = payload.get('project_name', '').strip()
    if project_name:
        # Exact match first
        project = Project.objects.filter(name__iexact=project_name).first()
        if project:
            return project
        # Partial match (contains, case-insensitive)
        project = Project.objects.filter(name__icontains=project_name).first()
        if project:
            return project

    return None


def _resolve_task(project, payload):
    task_id = payload.get('task_id')
    if task_id:
        try:
            return Task.objects.get(pk=int(task_id), project=project)
        except (Task.DoesNotExist, ValueError, TypeError):
            raise ValueError(f'Task {task_id} not found in project {project.name}')

    task_name = payload.get('task_name', '').strip()
    if task_name:
        task = Task.objects.filter(project=project, name__iexact=task_name).first()
        if task:
            return task
        raise ValueError(f'Task "{task_name}" not found in project {project.name}')

    raise ValueError('task_id or task_name is required')


def _resolve_stage(project, stage_value):
    """Optional stage resolver — returns None if not found or not provided."""
    if not stage_value:
        return None
    # Try as ID first
    try:
        return BuildStage.objects.get(pk=int(stage_value), project=project)
    except (ValueError, TypeError, BuildStage.DoesNotExist):
        pass
    # Try as name
    return BuildStage.objects.filter(project=project, name__iexact=str(stage_value)).first()


def _resolve_stage_required(project, payload):
    stage_id = payload.get('stage_id')
    if stage_id:
        try:
            return BuildStage.objects.get(pk=int(stage_id), project=project)
        except (BuildStage.DoesNotExist, ValueError, TypeError):
            raise ValueError(f'Stage {stage_id} not found in project {project.name}')

    stage_name = payload.get('stage_name', '').strip()
    if stage_name:
        stage = BuildStage.objects.filter(project=project, name__iexact=stage_name).first()
        if stage:
            return stage
        raise ValueError(f'Stage "{stage_name}" not found in project {project.name}')

    raise ValueError('stage_id or stage_name is required')


def _parse_date(val):
    if not val:
        return None
    try:
        return date.fromisoformat(str(val).strip())
    except (ValueError, TypeError):
        return None


def _parse_email_with_llm(raw_text, project):
    """Use Google Gemini to parse free-text into structured issue fields.
    Tries google-genai SDK first, falls back to REST API if not installed."""
    api_key = settings.GOOGLE_API_KEY
    if not api_key:
        raise ValueError('GOOGLE_API_KEY not configured — cannot parse raw_text')

    prompt = (
        'You are a project management assistant for an NPI (New Product Introduction) tracker.\n'
        'Parse the following email/message into a structured issue. Return ONLY valid JSON, no markdown.\n\n'
        f'Project context: "{project.name}"\n\n'
        'The JSON must have these fields:\n'
        '- "title": short summary of the issue (required, max 120 chars)\n'
        '- "severity": one of "critical", "high", "medium", "low" (infer from urgency/impact)\n'
        '- "owner": person responsible if mentioned, otherwise empty string\n'
        '- "due": deadline in ISO format (YYYY-MM-DD) if mentioned, otherwise null\n'
        '- "impact": business impact summary if mentioned, otherwise empty string\n'
        '- "desc": detailed description extracted from the text\n'
        '- "stage": build stage if mentioned (e.g. EVT, DVT, ETB, PVT, MP), otherwise null\n\n'
        'Email/message text:\n---\n'
        f'{raw_text[:3000]}\n'
        '---\n\nReturn ONLY the JSON object:'
    )

    raw_response = _call_gemini(api_key, prompt)
    return _parse_llm_json(raw_response)


def _call_gemini(api_key, prompt):
    """Call Gemini API — uses google-genai SDK if available, otherwise REST API."""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        logger.info('Gemini called via google-genai SDK')
        return response.text
    except ImportError:
        logger.info('google-genai not installed, using REST API fallback')
    except Exception as exc:
        logger.warning('google-genai SDK failed (%s), trying REST API fallback', exc)

    # Fallback: direct REST API via requests
    import requests as http
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}'
    body = {'contents': [{'parts': [{'text': prompt}]}]}
    resp = http.post(url, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data['candidates'][0]['content']['parts'][0]['text']


def _parse_llm_json(text):
    """Strip markdown fences and parse JSON from LLM response."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    if text.startswith('json'):
        text = text[4:].strip()

    try:
        parsed = json.loads(text)
        logger.info('LLM parsed email into: %s', parsed)
        return parsed
    except json.JSONDecodeError as exc:
        logger.warning('LLM returned invalid JSON: %s', exc)
        raise ValueError(f'LLM returned invalid JSON: {exc}')


def _record_error(webhook, msg):
    webhook.last_error = str(msg)[:500]
    webhook.last_received_at = timezone.now()
    webhook.save(update_fields=['last_error', 'last_received_at'])


# Handler registry
_HANDLERS = {
    'create_issue': _handle_create_issue,
    'update_task_status': _handle_update_task_status,
    'update_stage_status': _handle_update_stage_status,
    'create_task': _handle_create_task,
}
