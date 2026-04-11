from django.urls import path
from . import views
from .inbound import inbound_webhook_receive

urlpatterns = [
    # Portfolio
    path('', views.portfolio, name='portfolio'),

    # Project detail tabs
    path('project/<int:pk>/', views.project_detail, name='project-detail'),
    path('project/<int:pk>/gantt/', views.project_gantt, name='project-gantt'),
    path('project/<int:pk>/list/', views.project_list, name='project-list'),
    path('project/<int:pk>/milestones/', views.project_milestones, name='project-milestones'),
    path('project/<int:pk>/team/', views.project_team, name='project-team'),
    path('project/<int:pk>/stages/', views.project_stages, name='project-stages'),
    path('project/<int:pk>/nre/', views.project_nre, name='project-nre'),
    path('project/<int:pk>/issues/', views.project_issues, name='project-issues'),

    # Project CRUD
    path('project/create/', views.project_create, name='project-create'),

    # Section CRUD
    path('project/<int:pk>/sections/create/', views.section_create, name='section-create'),
    path('project/<int:pk>/sections/<int:sid>/edit/', views.section_edit, name='section-edit'),
    path('project/<int:pk>/sections/<int:sid>/delete/', views.section_delete, name='section-delete'),

    # Task CRUD
    path('project/<int:pk>/tasks/create/', views.task_create, name='task-create'),
    path('project/<int:pk>/tasks/<int:tid>/edit/', views.task_edit, name='task-edit'),
    path('project/<int:pk>/tasks/<int:tid>/delete/', views.task_delete, name='task-delete'),

    # Issue CRUD
    path('project/<int:pk>/issues/create/', views.issue_create, name='issue-create'),
    path('project/<int:pk>/issues/<int:iid>/edit/', views.issue_edit, name='issue-edit'),
    path('project/<int:pk>/issues/<int:iid>/delete/', views.issue_delete, name='issue-delete'),

    # Team CRUD
    path('project/<int:pk>/team/create/', views.member_create, name='member-create'),
    path('project/<int:pk>/team/<int:mid>/edit/', views.member_edit, name='member-edit'),
    path('project/<int:pk>/team/<int:mid>/delete/', views.member_delete, name='member-delete'),

    # NRE CRUD
    path('project/<int:pk>/nre/create/', views.nre_create, name='nre-create'),
    path('project/<int:pk>/nre/<int:nid>/edit/', views.nre_edit, name='nre-edit'),
    path('project/<int:pk>/nre/<int:nid>/delete/', views.nre_delete, name='nre-delete'),

    # Task issues modal
    path('project/<int:pk>/tasks/<int:tid>/issues/', views.task_issues_modal, name='task-issues-modal'),

    # Apply task template
    path('project/<int:pk>/apply-template/', views.template_apply, name='template-apply'),
    path('project/<int:pk>/apply-template/<int:set_pk>/preview/', views.template_preview, name='template-preview'),

    # Build Stage CRUD + gate toggle
    path('project/<int:pk>/stages/create/', views.stage_create, name='stage-create'),
    path('project/<int:pk>/stages/<int:sid>/edit/', views.stage_edit, name='stage-edit'),
    path('project/<int:pk>/stages/<int:sid>/delete/', views.stage_delete, name='stage-delete'),
    path('project/<int:pk>/stages/<int:sid>/gate/<int:gid>/toggle/', views.gate_toggle, name='gate-toggle'),

    # Portfolio issues modal
    path('project/<int:pk>/issues-modal/', views.project_issues_modal, name='project-issues-modal'),

    # Version control
    path('project/<int:pk>/history/', views.project_history, name='project-history'),
    path('project/<int:pk>/history/<int:vid>/', views.project_version_detail, name='project-version-detail'),
    path('project/<int:pk>/history/<int:vid>/restore/', views.project_version_restore, name='project-version-restore'),
    path('project/<int:pk>/commit/', views.project_commit, name='project-commit'),
    path('project/<int:pk>/commit/form/', views.project_commit_form, name='project-commit-form'),

    # API Endpoints
    path('api/tasks/<int:task_id>/', views.api_task_update, name='api-task-update'),
    path('api/tasks/<int:task_id>/link/', views.api_task_link, name='api-task-link'),
    path('api/tasks/<int:task_id>/unlink/', views.api_task_unlink, name='api-task-unlink'),

    # Power Automate Webhooks
    path('webhooks/', views.webhook_list, name='webhook-list'),
    path('webhooks/create/', views.webhook_create, name='webhook-create'),
    path('webhooks/<int:wid>/edit/', views.webhook_edit, name='webhook-edit'),
    path('webhooks/<int:wid>/delete/', views.webhook_delete, name='webhook-delete'),
    path('webhooks/<int:wid>/test/', views.webhook_test, name='webhook-test'),
    path('webhooks/<int:wid>/test-text/', views.webhook_test_text, name='webhook-test-text'),
    path('webhooks/<int:wid>/test-chat/', views.webhook_test_chat, name='webhook-test-chat'),

    # Called by Power Automate HTTP Webhook trigger (no login/CSRF)
    path('webhooks/pa/subscribe/<int:wid>/<str:token>/', views.webhook_pa_subscribe, name='webhook-pa-subscribe'),
    path('webhooks/pa/unsubscribe/<int:wid>/<str:token>/', views.webhook_pa_unsubscribe, name='webhook-pa-unsubscribe'),

    # Inbound Webhooks (receive events from Power Automate)
    path('api/inbound/<str:token>/', inbound_webhook_receive, name='inbound-webhook-receive'),
    path('webhooks/inbound/', views.inbound_webhook_list, name='inbound-webhook-list'),
    path('webhooks/inbound/create/', views.inbound_webhook_create, name='inbound-webhook-create'),
    path('webhooks/inbound/<int:wid>/edit/', views.inbound_webhook_edit, name='inbound-webhook-edit'),
    path('webhooks/inbound/<int:wid>/delete/', views.inbound_webhook_delete, name='inbound-webhook-delete'),
    path('webhooks/inbound/<int:wid>/regenerate/', views.inbound_webhook_regenerate, name='inbound-webhook-regenerate'),
]
