import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from jobs.youtube_job import run_youtube_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

log.info("Scheduler container started")

scheduler = BlockingScheduler(timezone="UTC")

scheduler.add_job(
    run_youtube_job,
    IntervalTrigger(hours=6),
    id="youtube_monitor",
    name="YouTube comment monitor",
    next_run_time=datetime.utcnow(),  # fire immediately on startup, then every 6h
)

log.info("YouTube monitor job registered — runs every 6 hours, first run starting now")

try:
    scheduler.start()
except (KeyboardInterrupt, SystemExit):
    log.info("Scheduler stopped")
