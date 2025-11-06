"""Schedule-based triggers using APScheduler.

Supports cron expressions for periodic workflow execution.
"""

from collections.abc import Callable
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger(__name__)


class TriggerScheduler:
    """Manage scheduled workflow triggers."""

    def __init__(self) -> None:
        """Initialize scheduler."""
        self.scheduler = AsyncIOScheduler()
        self.logger = logger.bind(component="trigger_scheduler")
        self._jobs: dict[str, str] = {}  # flow_id -> job_id mapping

    def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            self.logger.info("scheduler_started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.logger.info("scheduler_stopped")

    def add_schedule_trigger(
        self,
        flow_id: str,
        cron_expression: str,
        trigger_func: Callable,
        trigger_data: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a scheduled trigger for a flow.

        Args:
            flow_id: Flow ID to trigger
            cron_expression: Cron expression (e.g., "0 9 * * *" for 9am daily)
            trigger_func: Async function to call on trigger
            trigger_data: Optional data to pass to trigger function

        Returns:
            Job ID
        """
        try:
            # Parse cron expression
            # Format: minute hour day month day_of_week
            parts = cron_expression.split()
            if len(parts) != 5:
                raise ValueError(
                    "Cron expression must have 5 parts: minute hour day month day_of_week"
                )

            minute, hour, day, month, day_of_week = parts

            # Create trigger
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
            )

            # Add job
            job = self.scheduler.add_job(
                trigger_func,
                trigger=trigger,
                args=[flow_id, trigger_data or {}],
                id=f"flow_{flow_id}_schedule",
                name=f"Scheduled trigger for flow {flow_id}",
                replace_existing=True,
            )

            job_id_str = str(job.id)  # APScheduler job.id is Any, ensure it's a string
            self._jobs[flow_id] = job_id_str
            self.logger.info(
                "schedule_trigger_added", flow_id=flow_id, cron=cron_expression, job_id=job_id_str
            )

            return job_id_str

        except Exception as e:
            self.logger.error(
                "schedule_trigger_add_failed", flow_id=flow_id, cron=cron_expression, error=str(e)
            )
            raise

    def remove_schedule_trigger(self, flow_id: str) -> bool:
        """
        Remove scheduled trigger for a flow.

        Args:
            flow_id: Flow ID

        Returns:
            True if removed, False if not found
        """
        job_id = self._jobs.get(flow_id)
        if not job_id:
            return False

        try:
            self.scheduler.remove_job(job_id)
            del self._jobs[flow_id]
            self.logger.info("schedule_trigger_removed", flow_id=flow_id, job_id=job_id)
            return True
        except Exception as e:
            self.logger.error("schedule_trigger_remove_failed", flow_id=flow_id, error=str(e))
            return False

    def list_triggers(self) -> list[dict[str, Any]]:
        """
        List all scheduled triggers.

        Returns:
            List of trigger info dicts
        """
        triggers = []
        for job in self.scheduler.get_jobs():
            triggers.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return triggers
