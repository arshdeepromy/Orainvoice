# Bugfix Requirements Document

## Introduction

The billing and subscription lifecycle in OraInvoice has critical gaps affecting live production customers. Three lifecycle tasks (`check_trial_expiry_task`, `check_grace_period_task`, `check_suspension_retention_task`) are fully implemented in `app/tasks/subscriptions.py` but are never scheduled to run because they are missing from `_DAILY_TASKS` in `app/tasks/scheduled.py`. Additionally, they are missing from the `WRITE_TASKS` set, meaning even if scheduled they would not be skipped on standby nodes (risking replication conflicts in HA). On top of the scheduling gaps, several key lifecycle transitions lack email notifications: entering grace period, payment failure fallback (independent of Stripe webhooks), and data deletion after 90-day suspension.

The combined effect is that orgs in `grace_period` stay there forever, trials never auto-expire or send reminders, suspended orgs are never cleaned up, and org admins receive no notification at multiple critical billing transitions.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the scheduler loop runs THEN the system never executes `check_trial_expiry_task` because it is not registered in `_DAILY_TASKS` in `app/tasks/scheduled.py`, so trial orgs never receive 3-day reminder emails and trials never auto-convert to active status

1.2 WHEN the scheduler loop runs THEN the system never executes `check_grace_period_task` because it is not registered in `_DAILY_TASKS`, so orgs in `grace_period` status are never transitioned to `suspended` after 7 days

1.3 WHEN the scheduler loop runs THEN the system never executes `check_suspension_retention_task` because it is not registered in `_DAILY_TASKS`, so suspended orgs never receive 30-day or 7-day retention warnings and are never auto-deleted after 90 days

1.4 WHEN the three unscheduled tasks are absent from the `WRITE_TASKS` set THEN the system would not skip them on standby nodes if they were scheduled, risking write conflicts during HA replication

1.5 WHEN `process_recurring_billing_task` transitions an org from `active` to `grace_period` after 3 failed payment retries THEN the system sends no email to the org admin informing them their account has entered grace period

1.6 WHEN `process_recurring_billing_task` encounters a payment failure (PaymentFailedError or PaymentActionRequiredError) THEN the system does not send a fallback dunning email from the billing task itself, relying entirely on Stripe webhook `invoice.payment_failed` which may fail or be delayed

1.7 WHEN `check_suspension_retention_task` deletes an org after 90 days of suspension (setting status to `deleted`) THEN the system sends no final email to the org admin confirming their data has been deleted

### Expected Behavior (Correct)

2.1 WHEN the scheduler loop runs THEN the system SHALL execute `check_trial_expiry_task` at a regular interval (daily) by including it in `_DAILY_TASKS`, sending 3-day trial reminder emails and auto-converting expired trials to active status

2.2 WHEN the scheduler loop runs THEN the system SHALL execute `check_grace_period_task` at a regular interval (every 15 minutes, matching billing cadence) by including it in `_DAILY_TASKS`, transitioning orgs from `grace_period` to `suspended` after 7 days

2.3 WHEN the scheduler loop runs THEN the system SHALL execute `check_suspension_retention_task` at a regular interval (daily) by including it in `_DAILY_TASKS`, sending 30-day and 7-day retention warnings and auto-deleting orgs after 90 days of suspension

2.4 WHEN the three tasks are registered in `_DAILY_TASKS` THEN the system SHALL also include their task names in the `WRITE_TASKS` set so they are correctly skipped on standby nodes during HA replication

2.5 WHEN `process_recurring_billing_task` transitions an org from `active` to `grace_period` after 3 failed payment retries THEN the system SHALL send a grace period notification email to the org admin informing them their account is in trouble and they have 7 days to resolve payment

2.6 WHEN `process_recurring_billing_task` encounters a payment failure THEN the system SHALL send a fallback dunning email from the billing task itself (using the existing `send_dunning_email_task` function) so the org admin is notified even if the Stripe webhook fails or is delayed

2.7 WHEN `check_suspension_retention_task` deletes an org after 90 days of suspension THEN the system SHALL send a final data deletion confirmation email to the org admin before or immediately after setting the status to `deleted`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `process_recurring_billing_task` successfully charges an org THEN the system SHALL CONTINUE TO advance the next billing date, reset retry count, create a billing receipt, and send a receipt email exactly as it does today

3.2 WHEN `process_recurring_billing_task` encounters an org with no default payment method or no Stripe customer ID THEN the system SHALL CONTINUE TO skip that org and log a warning without crashing

3.3 WHEN the scheduler runs on a standby node THEN the system SHALL CONTINUE TO skip all tasks in `WRITE_TASKS` (including the newly added ones) and only run read-only tasks

3.4 WHEN `check_trial_expiry_task` finds a trial org with more than 3 days remaining THEN the system SHALL CONTINUE TO skip that org without sending a reminder or converting it

3.5 WHEN `check_grace_period_task` finds a grace period org with fewer than 7 days elapsed THEN the system SHALL CONTINUE TO skip that org without transitioning it to suspended

3.6 WHEN `check_suspension_retention_task` finds a suspended org with fewer than 30 days elapsed THEN the system SHALL CONTINUE TO skip that org without sending any warning

3.7 WHEN existing scheduled tasks (overdue invoices, retry notifications, recurring invoices, etc.) run THEN the system SHALL CONTINUE TO execute them at their configured intervals without any change to their behavior or scheduling

3.8 WHEN email sending fails for any of the new notification emails THEN the system SHALL CONTINUE TO log the failure and proceed without crashing the parent task, following the existing non-blocking email pattern used by `_send_billing_receipt_email`
