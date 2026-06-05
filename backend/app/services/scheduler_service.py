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

        # Weekly-email send queue — fire portal-scheduled campaigns once due.
        # Mailchimp's native scheduling is paid; instead the /schedule endpoint
        # parks a built draft locally (status='scheduled') and this job sends it
        # with the free campaigns.send when its time arrives. Polls every minute.
        self.scheduler.add_job(
            func=self._email_send_queue_job,
            trigger=IntervalTrigger(minutes=1),
            id='email_send_queue',
            name='Email Send Queue - fire portal-scheduled campaigns',
            replace_existing=True,
        )
        logger.info("✓ Scheduled: Email send queue check every minute")

        # Daily purchasing report — 07:00 America/Edmonton, Mon-Fri.
        self.scheduler.add_job(
            func=self._purchasing_report_job,
            trigger=CronTrigger(day_of_week='mon-fri', hour=7, minute=0, timezone='America/Edmonton'),
            id='purchasing_report',
            name='Daily Purchasing Report - shortfalls digest',
            replace_existing=True,
        )
        logger.info("✓ Scheduled: Daily purchasing report 07:00 America/Edmonton (Mon-Fri)")

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
        # NOTE: initial sales-order sync is invoked from main.lifespan via
        # `await bc_sync_service.sync_open_sales_orders_fast(...)` because
        # this method runs inside FastAPI's running event loop and asyncio
        # can't nest. The cron-scheduled firings of _sales_order_sync_job
        # run in BackgroundScheduler worker threads (no loop) so asyncio.run
        # works there.

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

    def _purchasing_report_job(self):
        """Refresh vendor mapping and email the daily purchasing digest.
        Default ON — only skipped if 'purchasing_report_enabled' is explicitly false."""
        db = None
        try:
            db = SessionLocal()
            from app.db.models import AppSettings
            setting = db.query(AppSettings).filter(
                AppSettings.setting_key == "purchasing_report_enabled"
            ).first()
            if setting is not None and not setting.setting_value:
                logger.info("Purchasing report disabled, skipping")
                return

            from app.services.vendor_map_service import vendor_map_service
            from app.services.purchasing_report_service import purchasing_report_service
            vendor_map_service.refresh(db)
            db.commit()
            result = purchasing_report_service.send_daily_report(db)
            logger.info(f"Purchasing report complete: {result}")
        except Exception as e:
            logger.error(f"Purchasing report job failed: {e}", exc_info=True)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    def _email_send_queue_job(self):
        """Send any portal-scheduled weekly-email campaigns whose time has come.

        The /api/email-agent/schedule endpoint builds the campaign as a Mailchimp
        draft and records it locally with status='scheduled' and scheduled_at (naive
        UTC). This poll finds rows that are due and fires the free campaigns.send,
        then flips the row to 'sent'. Each campaign is handled independently so one
        failure (e.g. a deleted draft) doesn't block the rest.
        """
        from datetime import datetime as _dt
        from app.db.models import EmailCampaign
        from app.config import settings

        db = None
        try:
            db = SessionLocal()
            now = _dt.utcnow()
            due = (
                db.query(EmailCampaign)
                .filter(
                    EmailCampaign.status == "scheduled",
                    EmailCampaign.scheduled_at != None,  # noqa: E711
                    EmailCampaign.scheduled_at <= now,
                )
                .all()
            )
            if not due:
                return

            mc_api_key = settings.MAILCHIMP_API_KEY
            mc_server = settings.MAILCHIMP_SERVER_PREFIX
            if not all([mc_api_key, mc_server]):
                logger.warning("Email send queue: %d due but Mailchimp not configured", len(due))
                return

            import mailchimp_marketing as MailchimpMarketing
            from mailchimp_marketing.api_client import ApiClientError

            client = MailchimpMarketing.Client()
            client.set_config({"api_key": mc_api_key, "server": mc_server})

            sent = 0
            for campaign in due:
                cid = campaign.mailchimp_campaign_id
                if not cid:
                    logger.error("Email send queue: campaign %s has no Mailchimp id, skipping", campaign.id)
                    campaign.status = "error"
                    continue
                try:
                    client.campaigns.send(cid)
                    campaign.status = "sent"
                    campaign.sent_at = _dt.utcnow()
                    sent += 1
                    logger.info("Email send queue: sent campaign %s (mc=%s)", campaign.id, cid)
                except ApiClientError as e:
                    logger.error("Email send queue: Mailchimp send failed for %s: %s", cid, e.text)
                    campaign.status = "error"
                except Exception as e:
                    logger.error("Email send queue: send failed for %s: %s", cid, e, exc_info=True)
                    campaign.status = "error"
            db.commit()
            if sent:
                logger.info("Email send queue: %d/%d campaign(s) sent", sent, len(due))
        except Exception as e:
            logger.error(f"Email send queue job failed: {e}", exc_info=True)
        finally:
            if db is not None:
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
