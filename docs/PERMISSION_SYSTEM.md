# Permission System Documentation

## Overview

The NPI Tracker uses a flexible, configurable role-based permission system. This replaces the previous hardcoded `UserProfile.role` field with a database-driven approach that allows administrators to define roles and permissions through the Django Admin interface without code changes.

## Core Concepts

### 1. Role

A **Role** defines a user type in the system (e.g., "Project Manager", "Engineer", "Customer").

**Fields:**
- `key` - Unique identifier used in code (e.g., `pm`, `engineer`, `customer`)
- `name` - Display name (e.g., "Project Manager")
- `description` - Optional description
- `is_superuser` - If true, bypasses all permission checks

**Default Roles:**
| Key | Name | Permissions |
|-----|------|-------------|
| `pm` | Project Manager | Full CRUD on all models |
| `engineer` | Engineer | View all, Add/Change on Task/Issue |
| `customer` | Customer | View only on Project/Task/Issue |

### 2. RolePermission

A **RolePermission** defines what a role can do on a specific model.

**Fields:**
- `role` - Foreign key to Role
- `model_name` - Model identifier (e.g., `project`, `task`, `issue`)
- `action` - Action type: `view`, `add`, `change`, `delete`

**Available Models:**
- `project`
- `buildstage`
- `milestone`
- `task`
- `issue`
- `teammember`
- `nreitem`
- `gatechecklistitem`
- `projectplanversion`
- `tasktemplateset`
- `webhookconfig`
- `inboundwebhook`

### 3. UserRoleAssignment

A **UserRoleAssignment** links users to roles with optional scope restrictions.

**Fields:**
- `user` - The Django user
- `role` - The assigned role
- `project` - Optional: if set, role only applies to this project
- `customer` - Optional: if set, user can only view projects for this customer

**Scopes:**
- **Global** (`project=None`): Role applies to all projects
- **Project-specific** (`project=Project`): Role only applies to the specified project
- **Customer-scoped** (`customer=Customer`): User can only access projects belonging to this customer

## Permission Checking

### In Views

Use the `@permission_required` decorator:

```python
from .permissions import permission_required

# Create projects (no project context needed)
@permission_required('project', 'add')
def project_create(request):
    ...

# Edit project-specific items
@permission_required('task', 'change', project_param='pk')
def task_edit(request, pk, tid):
    ...

# Delete with project context
@permission_required('issue', 'delete', project_param='pk')
def issue_delete(request, pk, iid):
    ...
```

### Programmatic Checks

```python
from .permissions import has_permission, can_view, can_add, can_change, can_delete

# Check specific permission
if has_permission(request.user, 'project', 'change'):
    # Show edit button

# Shorthand checks
if can_add(request.user, 'task', project):
    # Show "Add Task" button

if can_delete(request.user, 'nreitem', project):
    # Show delete option
```

### Project Queryset Filtering

```python
from .permissions import get_project_queryset

def portfolio(request):
    all_projects = Project.objects.all()
    # Filters based on user's customer assignment
    projects = get_project_queryset(request.user, all_projects)
```

## Managing Permissions

### Via Django Admin

1. Go to `/admin/core/role/`
   - Create new roles with unique keys
   - Mark as `is_superuser` for admin access

2. Go to `/admin/core/rolepermission/`
   - Define what each role can do on each model
   - Add granular permissions as needed

3. Go to `/admin/core/userroleassignment/`
   - Assign roles to users
   - Set project scope if needed
   - Set customer scope for customer users

### Common Permission Patterns

**Full Admin (PM):**
- Role: `pm`
- RolePermissions: All models, all actions (`view`, `add`, `change`, `delete`)
- Assignment: Global (project=None)

**Read-Only Engineer:**
- Role: `engineer` (or create `viewer`)
- RolePermissions: All models, `view` only
- Assignment: Global

**Project Manager for Single Project:**
- Role: `pm`
- RolePermissions: Full access
- Assignment: Project-specific (project=ProjectA)

**Customer Access:**
- Role: `customer`
- RolePermissions: `view` on project, task, issue
- Assignment: Global
- Customer: Set to specific customer record

## Migration from Old System

The migration `0021_permission_system` automatically:
1. Creates default roles (PM, Engineer, Customer)
2. Populates RolePermission with equivalent permissions
3. Creates UserRoleAssignment for existing UserProfile records
4. Transfers customer associations

**No manual data migration required.**

## Security Notes

1. **Superusers** bypass all permission checks
2. **Roles with `is_superuser=True`** bypass all permission checks
3. **Customer-scoped users** can only view projects belonging to their assigned customer
4. **Project-specific roles** only work within that project context

## Troubleshooting

**User can't access anything:**
- Check UserRoleAssignment exists for the user
- Verify RolePermission records exist for their role
- Check `is_active` on user account

**Permission denied on specific action:**
- Check RolePermission for (role, model_name, action) combination
- Verify project_param is correct in decorator

**Customer sees wrong projects:**
- Check UserRoleAssignment.customer field
- Verify project.customer is correctly set

## API Reference

### Decorators

```python
@permission_required(model_name, action, project_param=None)
```

- `model_name` - String: `project`, `task`, `issue`, etc.
- `action` - String: `view`, `add`, `change`, `delete`
- `project_param` - String: URL parameter name containing project_id (e.g., `'pk'`)

### Helper Functions

```python
has_permission(user, model_name, action, project=None) -> bool
can_view(user, model_name, project=None) -> bool
can_add(user, model_name, project=None) -> bool
can_change(user, model_name, project=None) -> bool
can_delete(user, model_name, project=None) -> bool
get_project_queryset(user, base_qs) -> QuerySet
can_view_project(user, project) -> bool
```
