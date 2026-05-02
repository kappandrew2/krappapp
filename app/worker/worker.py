import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(message)s")
log = logging.getLogger(__name__)

log.info("Worker container started — no jobs implemented in Phase 1")

while True:
    time.sleep(60)
