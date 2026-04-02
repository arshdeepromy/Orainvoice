# Project Management Module — Implementation Plan

Reference: Worklenz (github.com/Worklenz/worklenz) feature analysis mapped to OraInvoice integration.

## 1. Worklenz Feature Inventory

### 1.1 Core Project Management
| Feature | Worklenz Implementation | Our Current State |
|---------|------------------------|-------------------|
| Project CRUD | projects-controller.ts, projects table | Have: Project model, CRUD API, basic list/dashboard pages |
| Project statuses | sys_project_statuses table, project-statuses-controller | Have: simple string status (active/completed/on_hold/cancelled) |
| Project health | sys_project_healths table, project-healths-controller | Missing: no health tracking (on_track/at_risk/off_track) |
| Project categories | project_categories table, project-categories-controller | Missing |
| Project folders | project_folders table, project-folders-controller | Missing |
| Project members | project_members table, project-members-controller | Missing: no per-project member assignment |
| Project managers | project-managers-controller | Missing |
| Project subscribers | project_subscribers table | Missing |
| Project access levels | project_access_levels table | Missing: no project-level RBAC |
| Archived projects | archived_projects table | Missing |
| Favorite projects | favorite_projects table | Missing |
| Shared projects | shared-projects-controller | Missing |
| Project comments | project_comments, project_comment_mentions | Missing |
| Project templates | custom_project_templates, cpt_tasks, cpt_phases | Missing |
| Project insights | project-insights-controller (overdue tasks, member stats, status/priority graphs) | Have: basic profitability/progress |
| Project activity logs | project_logs table, activity-logs-controller | Have: basic activity feed |

### 1.2 Task Management (within Projects)
| Feature | Worklenz Implementation | Our Current State |
|---------|------------------------|-------------------|
| Tasks CRUD | tasks table, tasks-controller.ts | Missing: no task entity within projects |
| Task statuses | task_statuses table (per-project custom statuses with categories) | Missing |
| Task priorities | task_priorities table (urgent/high/medium/low/none) | Missing |
| Task assignees | tasks_assignees junction table | Missing |
| Task labels/tags | task_labels, team_labels tables | Missing |
| Task phases | task_phase junction, project_phases table | Missing |
| Sub-tasks | parent_task_id self-reference on tasks | Missing |
| Task dependencies | task_dependencies table (blocked_by type) | Missing |
| Task comments | task_comments, task_comment_contents, task_comment_mentions | Missing |
| Task attachments | task_attachments table | Missing |
| Task time tracking | task_timers (start/stop), task_work_log (manual entries) | Have: TimeSheet module (time entries linked to jobs, not project tasks) |
| Task estimation | total_minutes field on tasks | Missing |
| Task progress | progress tracking (manual/weighted/time-based modes) | Missing |
| Task recurring | task_recurring_schedules, task_recurring_templates | Missing |
| Task templates | task_templates, task_templates_tasks | Missing |
| Custom columns | cc_custom_columns, cc_column_values, cc_selection_options | Missing |
| Task sort ordering | sort_order field, drag-and-drop reordering | Missing |

### 1.3 Views & Visualizations
| Feature | Worklenz Implementation | Our Current State |
|---------|------------------------|-------------------|
| Task list view | task-list-table with grouping by status/priority/phase/label | Missing |
| Kanban board | board view with drag-drop between status columns | Missing |
| Gantt chart / Roadmap | gantt-controller, roadmap view with timeline bars | Missing |
| Workload view | project-workload controller, member allocation visualization | Missing |
| Schedule / Resource allocation | schedule controller, project_member_allocations table | Missing |
| Project updates/feed | project-view-updates with comments and activity | Have: basic activity feed |
| Project files | project-view-files for attachments | Missing |
| Project insights dashboard | Status/priority pie charts, overdue tasks, member stats, deadlines | Have: basic profitability dashboard |

### 1.4 Team & Collaboration
| Feature | Worklenz Implementation | Our Current State |
|---------|------------------------|-------------------|
| Teams/Workspaces | teams table (multi-team per user) | Have: organisations (single org per user session) |
| Team members | team_members table with roles | Have: org users with roles |
| Clients | clients table (linked to projects) | Have: customers (linked to projects) |
| Notifications | user_notifications, notification_settings | Have: notification module |
| Real-time updates | Socket.IO for live task/project changes | Missing: no WebSocket for project updates |
| Personal todo list | personal_todo_list table | Missing |
| Home page overview | home-page-controller (my tasks, recent projects) | Have: dashboard pages |

### 1.5 Reporting
| Feature | Worklenz Implementation | Our Current State |
|---------|------------------------|-------------------|
| Project reporting | reporting-controller (projects overview, members, tasks by status/priority) | Have: basic reports module |
| Reporting export | reporting-export-api-router | Have: CSV export |
| Time reports | Time tracking aggregation across projects | Have: TimeSheet module |

## 2. What We Already Have That Maps

### 2.1 Existing Backend Modules We Can Reuse
- **Projects module** (app/modules/projects/): CRUD, profitability, progress, activity feed — extend with tasks
- **Jobs module** (app/modules/jobs_v2/): Job cards with attachments, status tracking, time entries — similar pattern to tasks
- **Time tracking** (app/modules/time_tracking/): TimeSheet with entries — can link to project tasks
- **Staff module** (app/modules/staff/): Staff members — map to project members/assignees
- **Customers module** (app/modules/customers/): Customers — map to project clients
- **Notifications module** (app/modules/notifications/): Templates, reminders — extend for task notifications
- **Audit logging** (app/core/audit.py): Activity logs — extend for task activity
- **File uploads** (app/modules/uploads/): Encrypted file storage — use for task attachments
- **Expenses module** (app/modules/expenses/): Already links to projects via project_id

### 2.2 Existing Frontend Components We Can Reuse
- **ProjectList.tsx / ProjectDashboard.tsx**: Extend with task views
- **Job card patterns**: JobCardList, JobCardDetail, JobCardCreate — similar CRUD patterns for tasks
- **Time tracking UI**: TimeSheet.tsx — adapt for task time logging
- **Kanban-like patterns**: Job board (JobBoard.tsx) — adapt for task board view
- **Modal patterns**: All our existing modals (CreditNoteModal, RefundModal, etc.)
- **Table patterns**: InvoiceList split-panel, StockLevels table — reuse for task list
- **Drag-drop**: Not currently used but can add via react-beautiful-dnd or dnd-kit

## 3. Database Schema — New Tables Required

### 3.1 Core Task Tables
```sql
-- Task statuses per project (customizable per project)
CREATE TABLE project_task_statuses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280',
    category TEXT NOT NULL DEFAULT 'todo',  -- 'todo', 'doing', 'done'
    sort_order INTEGER DEFAULT 0,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task priorities (org-level)
CREATE TABLE task_priorities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,  -- 'urgent', 'high', 'medium', 'low', 'none'
    color TEXT DEFAULT '#6b7280',
    sort_order INTEGER DEFAULT 0
);

-- Tasks (the core entity)
CREATE TABLE project_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organisations(id),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_task_id UUID REFERENCES project_tasks(id) ON DELETE CASCADE,
    status_id UUID NOT NULL REFERENCES project_task_statuses(id),
    priority_id UUID REFERENCES task_priorities(id),
    name TEXT NOT NULL,
    description TEXT,
    task_key TEXT,  -- e.g. 'PROJ-001' auto-generated
    sort_order INTEGER DEFAULT 0,
    start_date DATE,
    due_date DATE,
    completed_date TIMESTAMPTZ,
    estimated_minutes INTEGER DEFAULT 0,
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    is_billable BOOLEAN DEFAULT TRUE,
    created_by UUID,
    assigned_to UUID,  -- primary assignee (staff member)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task assignees (multiple assignees per task)
CREATE TABLE project_task_assignees (
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (task_id, user_id)
);
```

### 3.2 Labels, Phases, Dependencies
```sql
-- Labels (org-level, reusable across projects)
CREATE TABLE project_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,
    color TEXT DEFAULT '#3b82f6',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task-label junction
CREATE TABLE project_task_labels (
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    label_id UUID NOT NULL REFERENCES project_labels(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, label_id)
);

-- Project phases (milestones/sprints)
CREATE TABLE project_phases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,
    color TEXT DEFAULT '#8b5cf6',
    start_date DATE,
    end_date DATE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task-phase junction
CREATE TABLE project_task_phases (
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    phase_id UUID NOT NULL REFERENCES project_phases(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, phase_id)
);

-- Task dependencies
CREATE TABLE project_task_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    dependency_type TEXT DEFAULT 'blocked_by',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.3 Comments, Attachments, Time Tracking
```sql
-- Task comments
CREATE TABLE project_task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task attachments (uses encrypted upload system)
CREATE TABLE project_task_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    file_key TEXT NOT NULL,  -- references /uploads/ encrypted file
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    uploaded_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task time entries (extends existing time tracking)
CREATE TABLE project_task_time_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    is_billable BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task activity log
CREATE TABLE project_task_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID,
    action TEXT NOT NULL,  -- 'created', 'status_changed', 'assigned', 'comment_added', etc.
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.4 Project Members & Settings
```sql
-- Project members (who has access to which project)
CREATE TABLE project_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID NOT NULL,
    role TEXT DEFAULT 'member',  -- 'owner', 'admin', 'member', 'viewer'
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, user_id)
);

-- Project favorites (per user)
CREATE TABLE project_favorites (
    user_id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, project_id)
);

-- Project categories (org-level grouping)
CREATE TABLE project_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organisations(id),
    name TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.5 Columns to Add to Existing `projects` Table
```sql
ALTER TABLE projects ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES project_categories(id);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS health TEXT DEFAULT 'on_track';  -- on_track, at_risk, off_track
ALTER TABLE projects ADD COLUMN IF NOT EXISTS color TEXT DEFAULT '#3b82f6';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS key TEXT;  -- short key like 'PROJ' for task numbering
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS notes TEXT;
```

## 4. Backend API Endpoints Required

### 4.1 Task CRUD (new router: app/modules/project_tasks/)
- `GET /api/v2/projects/{id}/tasks` — list tasks (filterable by status, priority, assignee, label, phase)
- `POST /api/v2/projects/{id}/tasks` — create task (quick-add or full form)
- `GET /api/v2/projects/{id}/tasks/{task_id}` — get task detail
- `PUT /api/v2/projects/{id}/tasks/{task_id}` — update task
- `DELETE /api/v2/projects/{id}/tasks/{task_id}` — delete task
- `PUT /api/v2/projects/{id}/tasks/{task_id}/status` — change status (real-time via WebSocket later)
- `PUT /api/v2/projects/{id}/tasks/{task_id}/assignees` — update assignees
- `PUT /api/v2/projects/{id}/tasks/{task_id}/labels` — update labels
- `PUT /api/v2/projects/{id}/tasks/{task_id}/sort-order` — reorder (drag-drop)
- `GET /api/v2/projects/{id}/tasks/{task_id}/subtasks` — list subtasks

### 4.2 Task Comments & Attachments
- `GET /api/v2/projects/{id}/tasks/{task_id}/comments` — list comments
- `POST /api/v2/projects/{id}/tasks/{task_id}/comments` — add comment
- `PUT /api/v2/projects/{id}/tasks/{task_id}/comments/{comment_id}` — edit comment
- `DELETE /api/v2/projects/{id}/tasks/{task_id}/comments/{comment_id}` — delete comment
- `POST /api/v2/projects/{id}/tasks/{task_id}/attachments` — upload attachment (uses encrypted upload system)
- `DELETE /api/v2/projects/{id}/tasks/{task_id}/attachments/{att_id}` — remove attachment

### 4.3 Task Time Tracking
- `POST /api/v2/projects/{id}/tasks/{task_id}/timer/start` — start timer
- `POST /api/v2/projects/{id}/tasks/{task_id}/timer/stop` — stop timer
- `POST /api/v2/projects/{id}/tasks/{task_id}/time-entries` — manual time entry
- `GET /api/v2/projects/{id}/tasks/{task_id}/time-entries` — list time entries

### 4.4 Project Configuration
- `GET /api/v2/projects/{id}/statuses` — list project task statuses
- `POST /api/v2/projects/{id}/statuses` — create custom status
- `PUT /api/v2/projects/{id}/statuses/{status_id}` — update status
- `DELETE /api/v2/projects/{id}/statuses/{status_id}` — delete status
- `GET /api/v2/projects/{id}/phases` — list phases
- `POST /api/v2/projects/{id}/phases` — create phase
- `GET /api/v2/projects/{id}/members` — list project members
- `POST /api/v2/projects/{id}/members` — add member
- `DELETE /api/v2/projects/{id}/members/{member_id}` — remove member

### 4.5 Labels & Priorities (org-level)
- `GET /api/v2/labels` — list org labels
- `POST /api/v2/labels` — create label
- `GET /api/v2/task-priorities` — list priorities
- `POST /api/v2/task-priorities` — create priority

### 4.6 Project Insights (extend existing)
- `GET /api/v2/projects/{id}/insights/overview` — status/priority distribution, overdue count
- `GET /api/v2/projects/{id}/insights/members` — tasks per member, workload
- `GET /api/v2/projects/{id}/insights/timeline` — deadline tracking, burndown

## 5. Frontend Pages & Components Required

### 5.1 New Pages
| Page | Description | Worklenz Reference |
|------|-------------|-------------------|
| ProjectView.tsx | Main project view with tab navigation (Tasks, Board, Roadmap, Members, Files, Insights, Updates) | projectView/project-view.tsx |
| ProjectViewTaskList.tsx | Task list with grouping, filtering, inline editing | taskList/ProjectViewTaskList.tsx |
| ProjectViewBoard.tsx | Kanban board with drag-drop between status columns | board/project-view-board.tsx |
| ProjectViewMembers.tsx | Project member management | members/project-view-members.tsx |
| ProjectViewInsights.tsx | Charts and stats dashboard | insights/project-view-insights.tsx |
| ProjectViewUpdates.tsx | Activity feed and comments | updates/ProjectViewUpdates.tsx |
| ProjectViewFiles.tsx | File attachments gallery | files/project-view-files.tsx |
| TaskDrawer.tsx | Slide-out panel for task detail/editing | components/task-drawer/ |

### 5.2 Reusable Components to Build
| Component | Description | Can Reuse From |
|-----------|-------------|---------------|
| TaskStatusBadge | Colored status pill | Our existing Badge component |
| TaskPriorityIcon | Priority indicator (flag icons) | New, simple |
| TaskAssigneeAvatars | Stacked avatar circles | Our existing avatar patterns |
| TaskLabelChips | Colored label tags | New, simple |
| QuickAddTask | Inline task creation row | Worklenz add-task-list-row pattern |
| TaskContextMenu | Right-click menu for task actions | New |
| TaskFilters | Filter bar (status, priority, assignee, label, search) | Our existing filter patterns |
| GroupBySelector | Group tasks by status/priority/phase/label | Worklenz GroupByFilterDropdown |
| DueDatePicker | Date picker with overdue highlighting | Our existing date inputs |
| TimeEstimation | Hours/minutes input for task estimation | New |
| ProgressBar | Task/project progress indicator | New, simple |

### 5.3 Integration Points with Existing UI
- **Sidebar navigation**: Add "Projects" section with task views
- **Dashboard**: Add "My Tasks" widget showing assigned tasks across projects
- **Job cards**: Link tasks to job cards (task can generate a job card)
- **Invoices**: Link tasks to invoice line items (billable task hours)
- **Time tracking**: Merge task time entries into existing TimeSheet view
- **Expenses**: Already linked via project_id — no change needed

## 6. Implementation Phases

### Phase 1: Core Task Management (Priority: High)
1. Database migration: project_tasks, project_task_statuses, task_priorities, project_task_assignees
2. Backend: Task CRUD service + router, status management, priority management
3. Frontend: ProjectView page with task list tab, QuickAddTask, TaskDrawer for detail editing
4. Frontend: Task filters (status, priority, assignee, search)
5. Extend existing ProjectList to show task counts per project

### Phase 2: Kanban Board & Labels (Priority: High)
1. Database migration: project_labels, project_task_labels
2. Backend: Label CRUD, task-label assignment
3. Frontend: Kanban board view with drag-drop between status columns
4. Frontend: Label management UI, label filter in task list

### Phase 3: Comments, Attachments & Time Tracking (Priority: Medium)
1. Database migration: project_task_comments, project_task_attachments, project_task_time_entries
2. Backend: Comment CRUD, attachment upload (reuse encrypted upload system), time entry CRUD + timer
3. Frontend: Comment thread in TaskDrawer, file upload zone, timer start/stop button
4. Integration: Merge task time entries into existing TimeSheet page

### Phase 4: Phases, Dependencies & Sub-tasks (Priority: Medium)
1. Database migration: project_phases, project_task_phases, project_task_dependencies
2. Backend: Phase CRUD, dependency management, sub-task support
3. Frontend: Phase column in task list, dependency visualization, sub-task expansion

### Phase 5: Project Members & Insights (Priority: Medium)
1. Database migration: project_members, project_favorites, project_categories, project_task_activity
2. Backend: Member management, insights aggregation queries
3. Frontend: Members tab, insights dashboard with charts, favorites/archive

### Phase 6: Advanced Views (Priority: Low)
1. Frontend: Gantt/Roadmap view (timeline visualization)
2. Frontend: Workload view (member allocation across projects)
3. Real-time updates via WebSocket (optional, can defer)

## 7. Key Architectural Decisions

### 7.1 Backend Stack Alignment
- Worklenz: Node.js/Express + raw PostgreSQL queries
- Our app: Python/FastAPI + SQLAlchemy async + Alembic migrations
- Decision: Implement all backend logic in our existing FastAPI patterns. No Node.js code will be copied — only the data model and API design are referenced.

### 7.2 Frontend Stack Alignment
- Worklenz: React + Ant Design (antd) + Redux Toolkit
- Our app: React + Tailwind CSS + custom components
- Decision: Build all UI with our existing Tailwind component library. Reference Worklenz component structure for feature completeness but implement with our design system.

### 7.3 Multi-tenancy
- Worklenz: team_id based isolation
- Our app: org_id based isolation with RLS
- Decision: All new tables include org_id with RLS policies, consistent with our existing pattern.

### 7.4 Real-time Updates
- Worklenz: Socket.IO for live task changes (50+ socket commands)
- Our app: No WebSocket infrastructure currently
- Decision: Defer real-time to Phase 6. Use optimistic UI updates + polling for now. When ready, add WebSocket via FastAPI's built-in WebSocket support.

### 7.5 Task Numbering
- Worklenz: task_no auto-increment per project
- Our app: Use project key + sequence (e.g., PROJ-001) similar to our invoice numbering pattern
- Decision: Reuse the gap-free sequence pattern from invoice_sequences table.

## 8. Files to Create (No Existing Files Modified)

### Backend
```
app/modules/project_tasks/
    __init__.py
    models.py          — ProjectTask, ProjectTaskStatus, TaskPriority, etc.
    schemas.py         — Pydantic schemas for all task operations
    service.py         — TaskService with CRUD, filtering, status transitions
    router.py          — All task API endpoints
    comment_service.py — Comment CRUD
    time_service.py    — Timer start/stop, manual entries

app/modules/project_config/
    __init__.py
    models.py          — ProjectLabel, ProjectPhase, ProjectMember, etc.
    schemas.py
    service.py
    router.py

alembic/versions/
    XXXX_create_project_task_tables.py
    XXXX_create_project_config_tables.py
    XXXX_extend_projects_table.py
```

### Frontend
```
frontend/src/pages/projects/
    ProjectView.tsx           — Main project view with tabs
    TaskList.tsx              — Task list with grouping and filters
    TaskBoard.tsx             — Kanban board view
    TaskDrawer.tsx            — Slide-out task detail panel
    ProjectMembers.tsx        — Member management
    ProjectInsights.tsx       — Charts and stats
    ProjectUpdates.tsx        — Activity feed
    ProjectFiles.tsx          — Attachments gallery

frontend/src/components/tasks/
    QuickAddTask.tsx           — Inline task creation
    TaskStatusBadge.tsx        — Status pill
    TaskPriorityIcon.tsx       — Priority flag
    TaskAssigneeAvatars.tsx    — Stacked avatars
    TaskLabelChips.tsx         — Label tags
    TaskFilters.tsx            — Filter bar
    TaskContextMenu.tsx        — Right-click actions
    TaskComments.tsx           — Comment thread
    TaskTimeTracker.tsx        — Timer + manual entry
```

## 9. Worklenz Features We Will NOT Implement

- Licensing/billing system (we have our own Stripe-based billing)
- AWS SES email integration (we have our own SMTP/email system)
- Survey system (not relevant to invoicing)
- Personal todo list (not core to project management in our context)
- Admin center user management (we have our own)
- Multi-language i18n (we can add later if needed)
- Custom project templates from Worklenz (we'll build our own simpler version)

## 10. Worklenz Code Reference Map — What to Copy/Adapt

This section maps exactly which Worklenz source files contain the logic to reference during implementation. The SQL can be adapted almost directly. Frontend component structure and state management patterns can be ported to our React/Tailwind stack.

### 10.1 Database — Direct SQL Adaptation
These files contain production-ready PostgreSQL that can be adapted with minimal changes (rename team_id to org_id, adjust naming conventions):

| Our Need | Worklenz Source File | What to Extract |
|----------|---------------------|-----------------|
| All core tables | `worklenz-backend/database/sql/1_tables.sql` | projects, tasks, task_statuses, task_priorities, task_labels, task_assignees, task_comments, task_attachments, task_timers, task_work_log, project_members, project_phases, task_dependencies, task_recurring |
| Views (task aggregations) | `worklenz-backend/database/sql/3_views.sql` | Task count views, member workload views, status distribution views |
| Functions (complex logic) | `worklenz-backend/database/sql/4_functions.sql` | Task ordering, status transitions, progress calculation, task numbering |
| Triggers (auto-updates) | `worklenz-backend/database/sql/triggers.sql` | Auto-update timestamps, cascade status changes, activity log triggers |
| Indexes (performance) | `worklenz-backend/database/sql/indexes.sql` | Composite indexes for task queries, covering indexes for list views |
| Progress calculation | `worklenz-backend/database/migrations/consolidated-progress-migrations.sql` | Manual/weighted/time-based progress modes |
| Sort order fixes | `worklenz-backend/database/migrations/fix_duplicate_sort_orders.sql` | Drag-drop sort order management |

### 10.2 Backend Controllers — Query Logic to Port to Python
Each controller contains the actual SQL queries and business logic. Port these to our FastAPI service layer:

| Feature | Worklenz Controller | Key Functions to Port |
|---------|--------------------|-----------------------|
| Task CRUD | `controllers/tasks-controller.ts` + `tasks-controller-v2.ts` | create, update, delete, getTasksByProject, getFilteredTasks |
| Task status changes | `controllers/task-statuses-controller.ts` | changeStatus, getByProject, createStatus, reorder |
| Task priorities | `controllers/task-priorities-controller.ts` | getPriorities, create, update |
| Sub-tasks | `controllers/sub-tasks-controller.ts` | getSubTasks, createSubTask, convertToSubTask |
| Task comments | `controllers/task-comments-controller.ts` | create, update, delete, getByTask, mentions |
| Task dependencies | `controllers/task-dependencies-controller.ts` | create, delete, getByTask |
| Task work log | `controllers/task-work-log-controller.ts` | logTime, getByTask, getByMember, deleteEntry |
| Task recurring | `controllers/task-recurring-controller.ts` | createSchedule, processRecurring |
| Labels | `controllers/labels-controller.ts` | CRUD, assignToTask, removeFromTask |
| Task phases | `controllers/task-phases-controller.ts` | CRUD, assignToTask |
| Project members | `controllers/project-members-controller.ts` | add, remove, changeRole, getByProject |
| Project insights | `controllers/project-insights-controller.ts` | getOverview, getMemberStats, getOverdueTasks, getTasksByStatus |
| Project comments | `controllers/project-comments-controller.ts` | CRUD with mentions |
| Project categories | `controllers/project-categories-controller.ts` | CRUD |
| Project folders | `controllers/project-folders-controller.ts` | CRUD, moveProject |
| Project health | `controllers/project-healths-controller.ts` | update, getOptions |
| Gantt/Roadmap | `controllers/project-roadmap/` | getTimeline, updateDates, dragResize |
| Workload | `controllers/project-workload/` | getMemberAllocations, getCapacity |
| Schedule | `controllers/schedule/` + `schedule-v2/` | getSchedule, allocateMember, updateAllocation |
| Reporting | `controllers/reporting/` | projectsOverview, memberOverview, tasksByStatus, tasksByPriority |
| Activity logs | `controllers/activity-logs-controller.ts` | getByProject, getByTask |
| Attachments | `controllers/attachment-controller.ts` | upload, delete, getByTask |
| Resource allocation | `controllers/resource-allocation-controller.ts` | allocate, deallocate, getByProject |

### 10.3 Frontend Components — Structure to Adapt
These are the most complex UI components. Port the component structure and state logic to our React/Tailwind stack:

| Our Component | Worklenz Source | What to Extract |
|--------------|-----------------|-----------------|
| Task list table | `pages/projects/projectView/taskList/task-list-table/task-list-table.tsx` | Column definitions, row rendering, inline editing, grouping logic |
| Task list cells | `pages/projects/projectView/taskList/task-list-table/task-list-table-cells/` (15 cell components) | Status cell, priority cell, assignee cell, date cells, estimation cell, progress cell, time tracker cell |
| Task list filters | `pages/projects/projectView/taskList/task-list-filters/task-list-filters.tsx` | Filter state management, filter UI, group-by logic |
| Group-by tables | `pages/projects/projectView/taskList/groupTables/TaskGroupList.tsx` | Grouping by status/priority/phase/label, collapsible groups |
| Quick add task | `pages/projects/projectView/taskList/task-list-table/task-list-table-rows/add-task-list-row.tsx` | Inline task creation UX |
| Sub-task rows | `pages/projects/projectView/taskList/task-list-table/task-list-table-rows/add-sub-task-list-row.tsx` | Sub-task expansion and creation |
| Kanban board | `pages/projects/projectView/board/project-view-board.tsx` | Board layout, column rendering, card rendering |
| Board cards | `pages/projects/projectView/board/board-section/board-task-card/` | Task card content, drag handle, quick actions |
| Board columns | `pages/projects/projectView/board/board-section/board-section-container.tsx` | Column header, card list, drop zone |
| Gantt/Roadmap | `pages/projects/project-view-1/roadmap/roadmap-grant-chart.tsx` | Timeline bar rendering, date calculations, drag resize |
| Roadmap table | `pages/projects/project-view-1/roadmap/roadmap-table/` | Task rows with timeline bars |
| Project insights | `pages/projects/projectView/insights/` | Overview graphs, member stats tables, overdue/deadline tables |
| Status overview chart | `pages/projects/projectView/insights/insights-overview/graphs/status-overview.tsx` | Pie/donut chart for status distribution |
| Priority overview chart | `pages/projects/projectView/insights/insights-overview/graphs/priority-overview.tsx` | Pie/donut chart for priority distribution |
| Member stats | `pages/projects/projectView/insights/insights-members/` | Tasks per member, assigned tasks list |
| Overdue tasks table | `pages/projects/projectView/insights/insights-tasks/tables/overdue-tasks-table.tsx` | Overdue task listing with days overdue |
| Project updates | `pages/projects/projectView/updates/ProjectViewUpdates.tsx` | Activity feed with comments |
| Project members | `pages/projects/projectView/members/project-view-members.tsx` | Member list, add/remove, role management |
| Project files | `pages/projects/projectView/files/project-view-files.tsx` | File gallery, upload, preview |
| Project view header | `pages/projects/projectView/project-view-header.tsx` | Tab navigation, project title, health indicator, favorite toggle |
| Project list | `pages/projects/project-list.tsx` | Project cards/rows, status badges, progress bars |
| Task drawer | `components/task-drawer/` | Slide-out panel for full task editing |
| Task context menu | `pages/projects/projectView/taskList/task-list-table/context-menu/task-context-menu.tsx` | Right-click actions |
| Custom columns | `pages/projects/projectView/taskList/task-list-table/custom-columns/` | Custom column modal, cell renderers, header |
| Time tracker cell | `pages/projects/projectView/taskList/task-list-table/task-list-table-cells/task-list-time-tracker-cell/` | Start/stop timer, display elapsed time |
| Progress cell | `pages/projects/projectView/taskList/task-list-table/task-list-table-cells/task-list-progress-cell/` | Progress bar with manual/auto modes |
| Enhanced kanban | `components/enhanced-kanban/` | Improved kanban with swimlanes |
| Advanced gantt | `components/advanced-gantt/` | Full gantt chart component |
| Schedule view | `components/schedule/` | Resource scheduling calendar |

### 10.4 Real-time Socket Events — Pattern Reference
These socket commands show exactly what real-time events to implement:

| Event | Worklenz Source | Purpose |
|-------|----------------|---------|
| Task status change | `socket.io/commands/on-task-status-change.ts` | Live status update across all viewers |
| Task name change | `socket.io/commands/on-task-name-change.ts` | Live inline edit sync |
| Task assignee change | `socket.io/commands/on-quick-assign-or-remove.ts` | Live assignee update |
| Task priority change | `socket.io/commands/on-task-priority-change.ts` | Live priority update |
| Task date changes | `socket.io/commands/on-task-start-date-change.ts`, `on-task-end-date-change.ts` | Live date updates |
| Task sort order | `socket.io/commands/on-task-sort-order-change.ts` | Live drag-drop reorder |
| Quick task create | `socket.io/commands/on-quick-task.ts` | Live new task appears for all viewers |
| Timer start/stop | `socket.io/commands/on-task-timer-start.ts`, `on-task-timer-stop.ts` | Live timer sync |
| Task labels change | `socket.io/commands/on-task-labels-change.ts` | Live label update |
| Task description | `socket.io/commands/on-task-description-change.ts` | Live description sync |
| Project status | `socket.io/commands/on-project-status-change.ts` | Live project status |
| Project health | `socket.io/commands/on-project-health-change.ts` | Live health indicator |
| Gantt drag | `socket.io/commands/on_gannt_drag_change.ts` | Live gantt bar resize |
| Schedule allocation | `socket.io/commands/on_schedule_member_allocation_create.ts` | Live resource allocation |

### 10.5 API Types — TypeScript Interfaces to Port
These type definitions document the exact data shapes:

| Types | Worklenz Source | Purpose |
|-------|----------------|---------|
| Project types | `types/project/` | Project, ProjectMember, ProjectStatus, ProjectHealth |
| Task types | `types/tasks/` | Task, TaskStatus, TaskPriority, TaskLabel, TaskAssignee |
| Reporting types | `types/reporting/` | ReportData, MemberReport, ProjectReport |
| Schedule types | `types/schedule/` | ScheduleEntry, Allocation, WorkloadData |
| Team types | `types/teamMembers/`, `types/teams/` | TeamMember, Team, Role |

### 10.6 Redux State Management — Feature Slices to Reference
These contain the client-side state management patterns:

| Feature | Worklenz Source | State Pattern |
|---------|----------------|---------------|
| Project state | `features/project/` | Current project, task list, filters, grouping |
| Task management | `features/task-management/`, `features/tasks/` | Task CRUD, optimistic updates |
| Board state | `features/board/`, `features/enhanced-kanban/` | Column state, drag state |
| Roadmap state | `features/roadmap/` | Timeline state, zoom level |
| Schedule state | `features/schedule/` | Allocation state, date range |
| Reporting state | `features/reporting/` | Report filters, cached data |
| Task drawer | `features/task-drawer/` | Open/close, current task, edit state |
