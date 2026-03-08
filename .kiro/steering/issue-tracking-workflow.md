---
inclusion: auto
---

# Issue Tracking & Regression Prevention Workflow

This steering file defines the mandatory process for handling errors, bugs, and issues in the OraInvoice/WorkshopPro codebase. Every error encountered — whether user-reported, discovered during development, or caught by tests — must follow this workflow.

## Issue Tracking Document

All issues are tracked in `#[[file:docs/ISSUE_TRACKER.md]]`. This file is the single source of truth for every bug found and fixed in the project.

## When an Error or Issue is Encountered

### Step 1: Log the Issue

Before doing anything else, add an entry to `docs/ISSUE_TRACKER.md` with:

- A sequential issue ID (e.g., `ISSUE-001`)
- Date discovered
- Severity: `critical` | `high` | `medium` | `low`
- Status: `open` | `investigating` | `fixing` | `resolved` | `regression`
- Summary of the error (what happened, error message, HTTP status, stack trace snippet)
- Where it was found (file path, endpoint, UI page)
- Root cause (fill in after investigation)
- Fix applied (fill in after fixing)
- Files changed (list every file modified to fix it)
- Related issues (link to any previous issues that touched the same code)

### Step 2: Check for Regressions from Previous Fixes

Before investigating the new bug, search the issue tracker for any previously resolved issues that:

- Touched the same files or modules
- Fixed similar symptoms
- Modified related code paths

If a previous fix exists in the same area, check whether the new bug is a regression caused by subsequent changes. If so, mark the new issue with `regression-of: ISSUE-XXX` and note what change reintroduced the problem.

### Step 3: Scan the Entire App for Similar Bugs

After understanding the root cause, scan the full codebase for the same pattern. Common patterns to check:

- Frontend/backend field name mismatches (e.g., `remember` vs `remember_me`)
- Missing or incorrect request/response schema alignment
- Inconsistent error handling patterns
- Missing null/undefined checks following the same pattern
- Copy-paste code that has the same flaw elsewhere

Use grep/search across both `app/` and `frontend/src/` directories. Fix ALL instances of the same bug pattern, not just the one reported.

### Step 4: Fix Using Spec Mode (for non-trivial bugs)

For bugs that are more than a one-line typo fix:

1. Create a bugfix spec under `.kiro/specs/` using the bugfix workflow
2. Document the bug condition, root cause, and fix strategy
3. Implement the fix through the spec task system
4. Record the spec name in the issue tracker entry

For trivial fixes (typos, single field renames), fix directly but still log in the issue tracker.

### Step 5: Update the Issue Tracker

After fixing, update the issue entry with:

- Status → `resolved`
- Root cause description
- Fix applied description
- All files changed
- Any related issues found during the scan
- Whether similar bugs were found and fixed elsewhere (list them as separate issues)

## When Making Any Code Change

Before committing any change, check `docs/ISSUE_TRACKER.md` for previously fixed issues in the same files. If your change touches files that were part of a previous fix, verify that:

1. The previous fix is still intact
2. Your change doesn't reintroduce the bug
3. The test or validation that confirmed the fix still passes

## Issue Entry Template

When adding a new issue, use this format:

```markdown
### ISSUE-XXX: [Short description]

- **Date**: YYYY-MM-DD
- **Severity**: critical | high | medium | low
- **Status**: open → investigating → fixing → resolved
- **Reporter**: user | developer | test-suite | agent
- **Regression of**: ISSUE-YYY (if applicable)

**Symptoms**: What the user saw or what failed

**Root Cause**: Why it happened

**Fix Applied**: What was changed to fix it

**Files Changed**:
- `path/to/file1`
- `path/to/file2`

**Similar Bugs Found & Fixed**:
- Description of similar pattern found in other files

**Related Issues**: ISSUE-YYY, ISSUE-ZZZ

**Spec**: `.kiro/specs/bugfix-name/` (if spec mode was used)
```

## Debug Code Cleanup

Any debug code added during investigation or fixing (console.log, debug comments, temporary variables, test endpoints, hardcoded values, etc.) MUST be removed once the fix is confirmed working. Before marking an issue as resolved:

1. Search all changed files for `console.log`, `console.debug`, `// DEBUG`, `// TODO: remove`, `// TEMP`
2. Remove any temporary logging, test scaffolding, or diagnostic code
3. Verify the fix still works after cleanup
4. Only then update the issue status to `resolved`

This applies to both frontend and backend code. Debug code left in production is itself a bug.

## Severity Guidelines

- **critical**: App crashes, data loss, security vulnerability, login broken, payments failing
- **high**: Major feature broken, blocking user workflow, incorrect data displayed
- **medium**: Feature partially broken, workaround exists, UI rendering issues
- **low**: Cosmetic issues, minor UX problems, non-blocking edge cases
