"""
Background Scheduler Service
Uses APScheduler to run periodic tasks like email monitoring
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

from app.services.email_monitor import email_monitor

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Manages background scheduled tasks
    """

    def __init__(self):
        """Initialize scheduler"""
        self.scheduler = BackgroundScheduler()
        self.is_running = False

    def start(self, email_check_interval_minutes: int = 15):
        """
        Start the background scheduler

        Args:
            email_check_interval_minutes: How often to check emails (default 15)
        """
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        logger.info("=" * 80)
        logger.info("Starting Background Scheduler")
        logger.info("=" * 80)

        # Add email monitoring job
        self.scheduler.add_job(
            func=self._check_emails_job,
            trigger=IntervalTrigger(minutes=email_check_interval_minutes),
            id='email_monitor',
            name='Email Monitor - Check for new quote requests',
            replace_existing=True
        )

        logger.info(f"✓ Scheduled: Email monitoring every {email_check_interval_minutes} minutes")

        # Start scheduler
        self.scheduler.start()
        self.is_running = True

        logger.info(f"✓ Scheduler started at {datetime.now()}")
        logger.info(f"✓ Next email check: {self._get_next_run_time('email_monitor')}")
        logger.info("=" * 80)

        # Run first check immediately
        logger.info("Running initial email check...")
        self._check_emails_job()

    def stop(self):
        """Stop the scheduler"""
        if not self.is_running:
            logger.warning("Scheduler not running")
            return

        logger.info("Stopping scheduler...")
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        logger.info("✓ Scheduler stopped")

    def _check_emails_job(self):
        """
        Job function that checks for new emails
        This is called by the scheduler
        """
        try:
            # Monitor all configured inboxes
            stats = email_monitor.monitor_inboxes(hours_back=1, max_emails_per_inbox=50)

            # Log summary
            if stats['quote_requests_parsed'] > 0:
                logger.info(f"Email check complete: {stats['quote_requests_parsed']} new quote(s) created")
            else:
                logger.info("Email check complete: No new quotes")

            # Log errors if any
            if stats['errors'] > 0:
                logger.warning(f"{stats['errors']} error(s) occurred during email check")

        except Exception as e:
            logger.error(f"Critical error in email monitor job: {str(e)}", exc_info=True)

    def _get_next_run_time(self, job_id: str) -> str:
        """Get next scheduled run time for a job"""
        job = self.scheduler.get_job(job_id)
        if job and job.next_run_time:
            return job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
        return "Unknown"

    def get_status(self) -> dict:
        """
        Get scheduler status

        Returns:
            Dictionary with scheduler status
        """
        jobs_status = []

        for job in self.scheduler.get_jobs():
            jobs_status.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None,
                'trigger': str(job.trigger)
            })

        return {
            'running': self.is_running,
            'jobs': jobs_status
        }


# Global singleton instance
_scheduler: SchedulerService = None


def get_scheduler() -> SchedulerService:
    """
    Get or create the global scheduler instance

    Returns:
        SchedulerService instance
    """
    global _scheduler

    if _scheduler is None:
        _scheduler = SchedulerService()

    return _scheduler
