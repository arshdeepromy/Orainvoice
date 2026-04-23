# Billing Lifecycle Gaps Bugfix Design

## Overview

Three billing lifecycle tasks (`check_trial_expiry_task`, `check_grace_period_task`, `check_suspension_retention_task`) are fully implemented in `app/tasks/subscriptions.py` but never execute because they are not registered in `_DAILY_TASKS` or `WRITE_TASKS` in `app/tasks/scheduled.py`. Additionally, several critical lifecycle transitions lack email notifications: entering grace period, payment failure fallback dunning, and data deletion confirmation.

The fix registers the three tasks in the scheduler with appropriate intervals, adds them to `WRITE_TASKS` for HA safety, and adds email sends at three missing notification points — all using existing helper functions and the established non-blocking email pattern.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — lifecycle tasks are implemented but never scheduled, and email notifications are missing at critical billing transitions
- **Property (P)**: The desired behavior — tasks run at their configured intervals and emails are sent at grace period entry, payment failure, and data deletion
- **Preservation**: Existing billing, receipt generation, payment processing, and scheduler behavior that must remain unchanged by the fix
- **`_DAILY_TASKS`**: The list in `app/tasks/scheduled.py` that the scheduler loop iterates to run tasks at configured intervals
- **`WRITE_TASKS`**: The set in `app/tasks/scheduled.py` of task names that must be skipped on standby nodes to prevent replication conflicts
- **`process_recurring_billing_task`**: The function in `app/tasks/subscriptions.py` that charges orgs on their billing cycle and transitions to grace period after 3 failures
- **`check_grace_period_task`**: The function that transitions orgs from `grace_period` to `suspended` after 7 days
- **`check_suspension_retention_task`**: The function that sends retention warnings and deletes orgs after 90 days of suspension
- **`check_trial_expiry_task`**: The function that sends 3-day trial reminders and auto-converts expired trials to active
- **`send_dunning_email_task`**: Existing helper that sends payment failure notification emails
- **`send_suspension_email_task`**: Existing helper that sends suspension/retention notification emails

## Bug Details

### Bug Condition

The bug manifests in two categories: (A) three lifecycle tasks exist but are never executed because they are not registered in the scheduler, and (B) three email notifications are never sent at critical billing transitions.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SchedulerCycleOrBillingEvent
  OUTPUT: boolean

  -- Category A: Task scheduling gap
  IF input.type == "scheduler_cycle" THEN
    RETURN input.taskName IN ['check_trial_expiry', 'check_grace_period', 'check_suspension_retention']
           AND input.taskName NOT IN _DAILY_TASKS
  END IF

  -- Category B: Missing email notifications
  IF input.type == "grace_period_entry" THEN
    RETURN org.status transitions from 'active' to 'grace_period'
           AND NOT gracePeriodEmailSent(org)
  END IF

  IF input.type == "payment_failure" THEN
    RETURN paymentFailed(org)
           AND NOT fallbackDunningEmailSent(org)
  END IF

  IF input.type == "data_deletion" THEN
    RETURN org.status transitions from 'suspended' to 'deleted'
           AND NOT deletionConfirmationEmailSent(org)
  END IF

  RETURN false
END FUNCTION
```

### Examples

- **Trial expiry never runs**: An org with `status='trial'` and `trial_ends_at` 2 days from now never receives a reminder email, and when the trial expires the org stays in `trial` status indefinitely
- **Grace period never checked**: An org transitions to `grace_period` after 3 failed payments, but `check_grace_period_task` never runs so the org stays in `grace_period` forever instead of being suspended after 7 days
- **Suspension retention never checked**: A suspended org is never sent 30-day or 7-day retention warnings, and is never auto-deleted after 90 days
- **No grace period entry email**: When `process_recurring_billing_task` sets `org.status = "grace_period"` after `MAX_BILLING_RETRIES`, no email is sent to the org admin
- **No fallback dunning email**: When a payment fails (attempt 1 or 2), the billing task does not send a dunning email — it relies entirely on Stripe webhooks which may fail or be delayed
- **No deletion confirmation email**: When `check_suspension_retention_task` sets `org.status = "deleted"` after 90 days, no final email is sent to the org admin

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `process_recurring_billing_task` successful charge flow must continue to advance `next_billing_date`, reset retry count, create `BillingReceipt`, and send receipt email exactly as today
- Orgs with no default payment method or no Stripe customer ID must continue to be skipped with a warning log
- Standby nodes must continue to skip all `WRITE_TASKS` (including the newly added ones) and only run read-only tasks
- `check_trial_expiry_task` must continue to skip trial orgs with more than 3 days remaining
- `check_grace_period_task` must continue to skip grace period orgs with fewer than 7 days elapsed
- `check_suspension_retention_task` must continue to skip suspended orgs with fewer than 30 days elapsed (no warning needed yet)
- All existing scheduled tasks (overdue invoices, retry notifications, recurring invoices, etc.) must continue to execute at their configured intervals without any change
- Email sending failures must continue to be logged and swallowed without crashing the parent task

**Scope:**
All inputs that do NOT involve the three unscheduled tasks or the three missing email notification points should be completely unaffected by this fix. This includes:
- Successful payment processing flow
- Stripe webhook-driven notifications
- All other scheduled tasks in `_DAILY_TASKS`
- Manual admin operations on organisations
- Frontend billing UI behavior

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Missing task registration in `_DAILY_TASKS`**: The three task functions (`check_trial_expiry_task`, `check_grace_period_task`, `check_suspension_retention_task`) are fully implemented in `app/tasks/subscriptions.py` but were never added to the `_DAILY_TASKS` list in `app/tasks/scheduled.py`. The scheduler loop in `_scheduler_loop()` only executes tasks listed in `_DAILY_TASKS`, so these tasks are dead code in production.

2. **Missing task names in `WRITE_TASKS`**: Even if the tasks were scheduled, their names are not in the `WRITE_TASKS` set. This means on standby nodes they would execute and write to the database, causing replication conflicts. All three tasks perform writes (status transitions, audit logs, email log entries).

3. **Missing email send in grace period transition**: In `process_recurring_billing_task`, the `PaymentFailedError`/`PaymentActionRequiredError` except block transitions the org to `grace_period` and writes an audit log, but never calls any email function to notify the org admin.

4. **Missing fallback dunning email on payment failure**: In the same except block, after incrementing `billing_retry_count`, no dunning email is sent. The existing `send_dunning_email_task` function is available but not called from the billing task — it's only called from the Stripe webhook handler in `app/modules/billing/router.py`.

5. **Missing deletion confirmation email**: In `check_suspension_retention_task`, when `days_suspended >= 90` triggers deletion, the code sets `org.status = "deleted"` and writes an audit log but sends no email. The existing `send_suspension_email_task` supports custom `email_type` values and could be extended, or a simple inline email can be sent.

## Correctness Properties

Property 1: Bug Condition - Lifecycle Tasks Execute on Schedule

_For any_ scheduler cycle where the scheduler loop iterates `_DAILY_TASKS`, the three lifecycle tasks (`check_trial_expiry_task`, `check_grace_period_task`, `check_suspension_retention_task`) SHALL be present in the list with appropriate intervals (daily for trial expiry and suspension retention, every 15 minutes for grace period) and SHALL execute when their interval elapses.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Condition - Tasks in WRITE_TASKS for HA Safety

_For any_ task registered in `_DAILY_TASKS` that performs database writes, its task name SHALL be present in the `WRITE_TASKS` set so that it is skipped on standby nodes during HA replication.

**Validates: Requirements 2.4**

Property 3: Bug Condition - Grace Period Entry Email Sent

_For any_ org where `process_recurring_billing_task` transitions the status from `active` to `grace_period` after `MAX_BILLING_RETRIES` failed payments, the system SHALL send a grace period notification email to the org admin using the non-blocking fire-and-forget pattern.

**Validates: Requirements 2.5**

Property 4: Bug Condition - Fallback Dunning Email Sent

_For any_ payment failure in `process_recurring_billing_task` (PaymentFailedError or PaymentActionRequiredError), the system SHALL call `send_dunning_email_task` with the current retry count to send a fallback dunning email, independent of Stripe webhooks.

**Validates: Requirements 2.6**

Property 5: Bug Condition - Data Deletion Confirmation Email Sent

_For any_ org where `check_suspension_retention_task` transitions the status from `suspended` to `deleted` after 90 days, the system SHALL send a data deletion confirmation email to the org admin before or immediately after setting the status.

**Validates: Requirements 2.7**

Property 6: Preservation - Existing Billing Flow Unchanged

_For any_ input where the bug condition does NOT hold (successful payments, orgs with no payment method, existing scheduled tasks), the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing billing, receipt generation, and scheduler functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/tasks/scheduled.py`

**Change 1: Add imports for the three task functions**
- Add imports for `check_trial_expiry_task`, `check_grace_period_task`, `check_suspension_retention_task` from `app.tasks.subscriptions`

**Change 2: Register tasks in `_DAILY_TASKS`**
- Add `(check_trial_expiry_task, 86400, "check_trial_expiry")` — daily cadence (trial expiry is not urgent)
- Add `(check_grace_period_task, 900, "check_grace_period")` — every 15 minutes (matches billing cadence, grace period transitions should be timely)
- Add `(check_suspension_retention_task, 86400, "check_suspension_retention")` — daily cadence (retention warnings and deletion are not urgent)

**Change 3: Add task names to `WRITE_TASKS`**
- Add `"check_trial_expiry"` to `WRITE_TASKS` (writes: status transitions, audit logs, email logs)
- Add `"check_grace_period"` to `WRITE_TASKS` (writes: status transitions, audit logs, email sends)
- Add `"check_suspension_retention"` to `WRITE_TASKS` (writes: status transitions, audit logs, settings updates, email sends)

---

**File**: `app/tasks/subscriptions.py`

**Change 4: Send grace period entry email in `process_recurring_billing_task`**
- In the `PaymentFailedError`/`PaymentActionRequiredError` except block, after the `if retry_count >= MAX_BILLING_RETRIES:` block that sets `org.status = "grace_period"`, add a fire-and-forget call to `send_suspension_email_task(org_id=str(org.id), email_type="grace_period")` wrapped in try/except with error logging
- This requires adding a `"grace_period"` entry to the `subjects` and `bodies` dicts in `send_suspension_email_task`

**Change 5: Send fallback dunning email on every payment failure**
- In the same except block, after incrementing `billing_retry_count` and before the `if retry_count >= MAX_BILLING_RETRIES:` check, add a fire-and-forget call to `send_dunning_email_task(org_id=str(org.id), attempt_count=retry_count)` wrapped in try/except with error logging
- This reuses the existing `send_dunning_email_task` function as-is

**Change 6: Send data deletion confirmation email in `check_suspension_retention_task`**
- In the `if days_suspended >= 90:` block, before or after setting `org.status = "deleted"`, add a fire-and-forget call to `send_suspension_email_task(org_id=str(org.id), email_type="data_deleted")` wrapped in try/except with error logging
- This requires adding a `"data_deleted"` entry to the `subjects` and `bodies` dicts in `send_suspension_email_task`

**Change 7: Extend `send_suspension_email_task` with new email types**
- Add `"grace_period"` to the `subjects` and `bodies` dicts with appropriate messaging (account in trouble, 7 days to resolve payment)
- Add `"data_deleted"` to the `subjects` and `bodies` dicts with appropriate messaging (data has been permanently deleted)

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that inspect `_DAILY_TASKS` and `WRITE_TASKS` for the missing task registrations, and mock the billing flow to verify emails are not sent at the three missing notification points. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Task Registration Test**: Assert `check_trial_expiry_task` is in `_DAILY_TASKS` — will fail on unfixed code because it's not registered
2. **Grace Period Task Registration Test**: Assert `check_grace_period_task` is in `_DAILY_TASKS` — will fail on unfixed code
3. **Suspension Retention Task Registration Test**: Assert `check_suspension_retention_task` is in `_DAILY_TASKS` — will fail on unfixed code
4. **WRITE_TASKS Coverage Test**: Assert all three task names are in `WRITE_TASKS` — will fail on unfixed code
5. **Grace Period Email Test**: Mock `process_recurring_billing_task` with 3 failed payments and assert a grace period email is sent — will fail on unfixed code
6. **Dunning Email Test**: Mock a payment failure and assert `send_dunning_email_task` is called from the billing task — will fail on unfixed code
7. **Deletion Email Test**: Mock `check_suspension_retention_task` with a 90-day suspended org and assert a deletion email is sent — will fail on unfixed code

**Expected Counterexamples**:
- `_DAILY_TASKS` does not contain entries for the three lifecycle tasks
- `WRITE_TASKS` does not contain the three task names
- No email functions are called in the payment failure except block or the deletion block

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  IF input.type == "scheduler_cycle" THEN
    ASSERT input.taskName IN _DAILY_TASKS
    ASSERT input.taskName IN WRITE_TASKS
  END IF
  IF input.type == "grace_period_entry" THEN
    result := process_recurring_billing_task_fixed(input)
    ASSERT gracePeriodEmailSent(result)
  END IF
  IF input.type == "payment_failure" THEN
    result := process_recurring_billing_task_fixed(input)
    ASSERT dunningEmailSent(result)
  END IF
  IF input.type == "data_deletion" THEN
    result := check_suspension_retention_task_fixed(input)
    ASSERT deletionEmailSent(result)
  END IF
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT process_recurring_billing_task_original(input) = process_recurring_billing_task_fixed(input)
  ASSERT _scheduler_loop_original(input) = _scheduler_loop_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for successful payments, skipped orgs, and existing scheduled tasks, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Successful Payment Preservation**: Observe that successful billing charges advance `next_billing_date`, create receipts, and send receipt emails on unfixed code, then verify this continues after fix
2. **Skipped Org Preservation**: Observe that orgs with no payment method or no Stripe customer ID are skipped on unfixed code, then verify this continues after fix
3. **Existing Task Preservation**: Observe that all existing `_DAILY_TASKS` entries remain unchanged and execute at their configured intervals after fix
4. **Standby Skip Preservation**: Observe that standby nodes skip `WRITE_TASKS` on unfixed code, then verify the newly added tasks are also skipped on standby

### Unit Tests

- Test that `_DAILY_TASKS` contains all three new task entries with correct intervals
- Test that `WRITE_TASKS` contains all three new task names
- Test that `send_suspension_email_task` handles `"grace_period"` and `"data_deleted"` email types
- Test that payment failure in billing task triggers both dunning email and (on final retry) grace period email
- Test that email failures in new notification points are caught and logged without crashing

### Property-Based Tests

- Generate random org states (trial, active, grace_period, suspended) with random dates and verify the correct lifecycle task would process them correctly
- Generate random payment failure scenarios (retry counts 1-3) and verify the correct emails are sent at each stage
- Generate random scheduler cycles and verify all `_DAILY_TASKS` entries are present and `WRITE_TASKS` is a superset of all write-performing task names

### Integration Tests

- Test full billing lifecycle: trial → active → grace_period → suspended → deleted, verifying emails at each transition
- Test scheduler loop with mocked tasks, verifying all tasks execute at their intervals and standby skipping works
- Test that the three new tasks produce correct results when run against test org data in each lifecycle state
