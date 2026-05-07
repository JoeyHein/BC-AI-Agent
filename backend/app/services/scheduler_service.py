"""
Background Scheduler Service
Uses APScheduler to run periodic tasks like email monitoring
"""

import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

from app.services.email_monitor import email_monitor
from app.db.database import SessionLocal

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

        # Add catalog builder nightly sync (runs at 2 AM daily)
        self.scheduler.add_job(
            func=self._catalog_sync_job,
            trigger=IntervalTrigger(hours=24),
            id='catalog_builder',
            name='Catalog Builder - Nightly BC item sync',
            replace_existing=True
        )
        logger.info("✓ Scheduled: Catalog builder nightly sync")

        # Add inventory review agent (every 6 hours)
        self.scheduler.add_job(
            func=self._inventory_review_job,
            trigger=IntervalTrigger(hours=6),
            id='inventory_review',
            name='Inventory Review Agent - Stock analysis',
            replace_existing=True
        )
        logger.info("✓ Scheduled: Inventory review every 6 hours")

        # Add PO generation agent (every 12 hours)
        self.scheduler.add_job(
            func=self._po_generation_job,
            trigger=IntervalTrigger(hours=12),
            id='po_generation',
            name='PO Generation Agent - Draft purchase orders',
            replace_existing=True
        )
        logger.info("✓ Scheduled: PO generation every 12 hours")

        # Sales order sync — every 2 hours during business hours, Mon-Fri.
        # Skips overnight to avoid hammering BC when nobody's looking at the
        # Order Age Tracker.
        self.scheduler.add_job(
            func=self._sales_order_sync_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour='8,10,12,14,16,18',
                minute=0,
                timezone='America/Edmonton',
            ),
            id='sales_order_sync',
            name='BC Sales Order Sync - Open orders for tracker',
            replace_existing=True,
        )
        logger.info("✓ Scheduled: Sales order sync every 2 hours, 08:00-18:00 America/Edmonton (Mon-Fri)")

        # Start scheduler
        self.scheduler.start()
        self.is_running = True

        logger.info(f"✓ Scheduler started at {datetime.now()}")
        logger.info(f"✓ Next email check: {self._get_next_run_time('email_monitor')}")
        logger.info(f"✓ Next order sync: {self._get_next_run_time('sales_order_sync')}")
        logger.info("=" * 80)

        # Run first check immediately
        logger.info("Running initial email check...")
        self._check_emails_job()
        # Also run an initial order sync so the tracker has data on startup
        # rather than waiting for the next 2-hour tick.
        logger.info("Running initial sales order sync...")
        self._sales_order_sync_job()

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

    def _catalog_sync_job(self):
        """Run catalog builder pipeline if enabled."""
        try:
            db = SessionLocal()
            from app.db.models import AppSettings
            setting = db.query(AppSettings).filter(AppSettings.setting_key == "catalog_builder_enabled").first()
            if not setting or not setting.setting_value:
                logger.info("Catalog builder disabled, skipping")
                db.close()
                return
            db.close()

            from app.services.catalog_builder_service import catalog_builder_service
            db = SessionLocal()
            stats = catalog_builder_service.run_pipeline(db)
            db.commit()
            logger.info(f"Catalog sync complete: {stats}")
        except Exception as e:
            logger.error(f"Catalog sync job failed: {e}", exc_info=True)
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _inventory_review_job(self):
        """Run inventory review if enabled."""
        try:
            db = SessionLocal()
            from app.db.models import AppSettings
            setting = db.query(AppSettings).filter(AppSettings.setting_key == "inventory_agent_enabled").first()
            if not setting or not setting.setting_value:
                logger.info("Inventory review agent disabled, skipping")
                db.close()
                return
            db.close()

            from app.services.inventory_review_service import inventory_review_service
            db = SessionLocal()
            stats = inventory_review_service.run_review(db)
            db.commit()
            logger.info(f"Inventory review complete: {stats}")
        except Exception as e:
            logger.error(f"Inventory review job failed: {e}", exc_info=True)
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _po_generation_job(self):
        """Run PO generation if enabled."""
        try:
            db = SessionLocal()
            from app.db.models import AppSettings
            setting = db.query(AppSettings).filter(AppSettings.setting_key == "po_agent_enabled").first()
            if not setting or not setting.setting_value:
                logger.info("PO generation agent disabled, skipping")
                db.close()
                return
            db.close()

            from app.services.po_agent_service import po_agent_service
            db = SessionLocal()
            stats = po_agent_service.run_po_generation(db)
            db.commit()
            logger.info(f"PO generation complete: {stats}")
        except Exception as e:
            logger.error(f"PO generation job failed: {e}", exc_info=True)
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _sales_order_sync_job(self):
        """Bulk-sync BC sales-order headers into the local SalesOrder table.
        Powers the Order Age Tracker dashboard."""
        from app.services.bc_sync_service import bc_sync_service
        db = None
        try:
            db = SessionLocal()
            stats = asyncio.run(bc_sync_service.sync_open_sales_orders_fast(db))
            logger.info(
                f"Sales order sync: {stats.get('orders_synced', 0)} new, "
                f"{stats.get('orders_updated', 0)} updated, "
                f"{len(stats.get('errors', []))} errors"
            )
            if stats.get("errors"):
                logger.warning(f"Sales order sync errors: {stats['errors'][:3]}")
        except Exception as e:
            logger.error(f"Sales order sync job failed: {e}", exc_info=True)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

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
