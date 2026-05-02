import logging
import os

from jobs.ebay_etl_job import scan_existing_files, watch_imports_folder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(message)s")
log = logging.getLogger(__name__)

log.info("Worker container started")

folder = os.environ.get("EBAY_IMPORT_FOLDER", "/app/imports")
scan_existing_files(folder)
watch_imports_folder()
