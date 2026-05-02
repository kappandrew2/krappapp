import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [scheduler] %(message)s")
log = logging.getLogger(__name__)

log.info("Scheduler container started — no jobs scheduled in Phase 1")

while True:
    time.sleep(60)
