"""Background job priority queue for Celery task routing.

Provides JobPriorityQueue that classifies tasks into high, medium, and
low priority queues with configurable worker allocation ratios.

High-priority tasks (payments, POS) are processed before lower-priority
tasks (reports, analytics).

Requirements: 43.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Priority(str, Enum):
    """Task priority levels mapped to Celery queue names."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Maps task categories to priority levels
TASK_PRIORITY_MAP: dict[str, Priority] = {
    # High priority — time-sensitive financial operations
    "payments": Priority.HIGH,
    "pos": Priority.HIGH,
    "pos_transactions": Priority.HIGH,
    "payment_processing": Priority.HIGH,
    "stripe_webhooks": Priority.HIGH,
    # Medium priority — standard business operations
    "invoices": Priority.MEDIUM,
    "sync": Priority.MEDIUM,
    "notifications": Priority.MEDIUM,
    "pdf_generation": Priority.MEDIUM,
    "woocommerce_sync": Priority.MEDIUM,
    "recurring_invoices": Priority.MEDIUM,
    # Low priority — background analytics and reporting
    "reports": Priority.LOW,
    "analytics": Priority.LOW,
    "data_export": Priority.LOW,
    "archive": Priority.LOW,
    "compliance_check": Priority.LOW,
}

# Celery queue names for each priority level
PRIORITY_QUEUE_MAP: dict[Priority, str] = {
    Priority.HIGH: "high_priority",
    Priority.MEDIUM: "default",
    Priority.LOW: "bulk",
}


@dataclass
class WorkerAllocation:
    """Configurable worker allocation per priority level.

    Ratios determine how many workers (out of total) are assigned
    to each priority queue. E.g. with 10 workers and ratios 5:3:2,
    5 workers handle high, 3 medium, 2 low.
    """

    high: int = 5
    medium: int = 3
    low: int = 2

    @property
    def total(self) -> int:
        return self.high + self.medium + self.low

    def as_concurrency_map(self, total_workers: int) -> dict[str, int]:
        """Return queue → worker count for a given total worker pool."""
        ratio_total = self.total
        return {
            PRIORITY_QUEUE_MAP[Priority.HIGH]: max(
                1, round(total_workers * self.high / ratio_total)
            ),
            PRIORITY_QUEUE_MAP[Priority.MEDIUM]: max(
                1, round(total_workers * self.medium / ratio_total)
            ),
            PRIORITY_QUEUE_MAP[Priority.LOW]: max(
                1, round(total_workers * self.low / ratio_total)
            ),
        }


@dataclass
class JobPriorityQueue:
    """Routes tasks to priority-based Celery queues.

    Usage::

        queue = JobPriorityQueue()
        queue_name = queue.get_queue("payments")
        # → "high_priority"

        task.apply_async(queue=queue_name)
    """

    priority_map: dict[str, Priority] = field(
        default_factory=lambda: dict(TASK_PRIORITY_MAP)
    )
    worker_allocation: WorkerAllocation = field(
        default_factory=WorkerAllocation
    )

    def get_queue(self, task_category: str) -> str:
        """Return the Celery queue name for a task category."""
        priority = self.priority_map.get(task_category, Priority.MEDIUM)
        return PRIORITY_QUEUE_MAP[priority]

    def get_priority(self, task_category: str) -> Priority:
        """Return the priority level for a task category."""
        return self.priority_map.get(task_category, Priority.MEDIUM)

    def register_category(self, category: str, priority: Priority) -> None:
        """Register or update a task category's priority."""
        self.priority_map[category] = priority

    def route_task(self, task_category: str, **apply_kwargs: Any) -> dict[str, Any]:
        """Return kwargs dict for ``task.apply_async()`` with queue set.

        Usage::

            task.apply_async(**queue.route_task("payments", args=[...]))
        """
        queue_name = self.get_queue(task_category)
        return {**apply_kwargs, "queue": queue_name}

    def get_celery_queues(self):
        """Return Kombu Queue objects for all priority queues.

        Use to extend TASK_QUEUES in the Celery configuration.
        """
        from kombu import Exchange, Queue

        return (
            Queue(
                "high_priority",
                Exchange("high_priority", type="direct"),
                routing_key="high_priority",
            ),
            Queue(
                "bulk",
                Exchange("bulk", type="direct"),
                routing_key="bulk",
            ),
        )


# Module-level singleton
job_queue = JobPriorityQueue()
