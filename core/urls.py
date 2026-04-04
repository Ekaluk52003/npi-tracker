from django.urls import path
from . import views

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

    # Build Stage edit + gate toggle
    path('project/<int:pk>/stages/<str:stage_id>/edit/', views.stage_edit, name='stage-edit'),
    path('project/<int:pk>/stages/<str:stage_id>/gate/<int:gid>/toggle/', views.gate_toggle, name='gate-toggle'),

    # Portfolio issues modal
    path('project/<int:pk>/issues-modal/', views.project_issues_modal, name='project-issues-modal'),
]
