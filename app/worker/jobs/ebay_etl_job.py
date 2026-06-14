import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from db import get_connection

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent.parent
CONFIG_DIR = _HERE / "config"
COLUMN_MAP_PATH = CONFIG_DIR / "ebay_column_map.json"
STOP_WORDS_PATH = CONFIG_DIR / "stop_words.json"

IMPORTS_FOLDER = os.environ.get("EBAY_IMPORT_FOLDER", "/app/imports")

REQUIRED_COLUMNS = {
    "active": {"item_number", "title", "start_date"},
    "sold": {"item_number", "item_title", "sale_date"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_column_map() -> dict:
    with open(COLUMN_MAP_PATH) as f:
        return json.load(f)


def _load_stop_words() -> set:
    with open(STOP_WORDS_PATH) as f:
        return set(json.load(f))


def detect_file_type(filename: str) -> str | None:
    name = filename.lower()
    if "active" in name:
        return "active"
    if "sold" in name:
        return "sold"
    return None


def _already_loaded(conn, filename: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM ebay_load_history WHERE filename = %s", (filename,))
        return cur.fetchone() is not None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + underscore all column names, strip special chars."""
    df.columns = [
        re.sub(r"[^a-z0-9]+", "_", col.strip().lower()).strip("_")
        for col in df.columns
    ]
    return df


# ---------------------------------------------------------------------------
# 1. Read file
# ---------------------------------------------------------------------------

def read_file(filepath: str, file_type: str) -> pd.DataFrame:
    ext = Path(filepath).suffix.lower()
    skiprows = 1 if file_type == "sold" else 0
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(filepath, skiprows=skiprows, dtype=str)
    return pd.read_csv(filepath, skiprows=skiprows, dtype=str)


# ---------------------------------------------------------------------------
# 2. Validate and normalize
# ---------------------------------------------------------------------------

def validate_and_normalize(df: pd.DataFrame, file_type: str) -> pd.DataFrame:
    column_map = _load_column_map()[file_type]

    df = normalize_columns(df)
    log.info("[%s] Columns found: %s", file_type, list(df.columns))

    missing = REQUIRED_COLUMNS[file_type] - set(df.columns)
    if missing:
        raise ValueError(
            f"[{file_type}] Missing required columns: {sorted(missing)}\n"
            f"Actual columns found: {sorted(df.columns.tolist())}\n"
            f"Update app/worker/config/ebay_column_map.json to match."
        )

    # Track which columns are unmapped before renaming
    unmapped_cols = [c for c in df.columns if c not in column_map]

    df = df.rename(columns=column_map)

    # Date parsing
    if "listing_date" in df.columns:
        df["listing_date"] = pd.to_datetime(
            df["listing_date"], errors="coerce"
        ).dt.date
    if "end_date" in df.columns:
        df["end_date"] = pd.to_datetime(
            df["end_date"].astype(str).str.replace(
                r"\s+(PDT|PST|EDT|EST|CDT|CST|MDT|MST)", "", regex=True
            ),
            errors="coerce",
        ).dt.date
    if "sold_date" in df.columns:
        df["sold_date"] = pd.to_datetime(
            df["sold_date"], format="%b-%d-%y", errors="coerce"
        ).dt.date

    # Numeric parsing — strip $ and commas before casting
    for col in ("price", "sold_price"):
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(r"[^\d.]", "", regex=True)
                .pipe(pd.to_numeric, errors="coerce")
            )
    if "sold_quantity" in df.columns:
        df["sold_quantity"] = pd.to_numeric(df["sold_quantity"], errors="coerce")

    # Strip whitespace from all text columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip().replace("nan", None)

    # Pack unmapped columns into raw_data JSONB
    if unmapped_cols:
        def _to_raw(row):
            return json.dumps(
                {k: row[k] for k in unmapped_cols if row[k] not in (None, "nan", "")}
            )
        df["raw_data"] = df.apply(_to_raw, axis=1)
    else:
        df["raw_data"] = "{}"

    return df


# ---------------------------------------------------------------------------
# 3. Upsert
# ---------------------------------------------------------------------------

def upsert_items(conn, df: pd.DataFrame, file_type: str) -> dict:
    inserted = updated = 0

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            item_id = str(row.get("ebay_item_id") or "").strip()
            if not item_id:
                continue

            raw = row.get("raw_data", "{}")

            if file_type == "active":
                cur.execute(
                    """
                    INSERT INTO ebay_items (
                        ebay_item_id, title, category, status,
                        listing_date, end_date, price, condition,
                        raw_data, last_loaded_at, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s, NOW(), NOW(), NOW())
                    ON CONFLICT (ebay_item_id) DO UPDATE SET
                        title          = EXCLUDED.title,
                        category       = EXCLUDED.category,
                        end_date       = EXCLUDED.end_date,
                        price          = EXCLUDED.price,
                        condition      = EXCLUDED.condition,
                        raw_data       = EXCLUDED.raw_data,
                        last_loaded_at = NOW(),
                        updated_at     = NOW()
                    RETURNING id, (xmax = 0) AS is_new
                    """,
                    (
                        item_id,
                        row.get("title"),
                        row.get("category"),
                        row.get("listing_date") or None,
                        row.get("end_date") or None,
                        row.get("price") or None,
                        row.get("condition"),
                        raw,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO ebay_items (
                        ebay_item_id, title, status,
                        sold_date, sold_price, sold_quantity,
                        raw_data, last_loaded_at, created_at, updated_at
                    )
                    VALUES (%s, %s, 'sold', %s, %s, %s, %s, NOW(), NOW(), NOW())
                    ON CONFLICT (ebay_item_id) DO UPDATE SET
                        title          = EXCLUDED.title,
                        status         = 'sold',
                        sold_date      = EXCLUDED.sold_date,
                        sold_price     = EXCLUDED.sold_price,
                        sold_quantity  = EXCLUDED.sold_quantity,
                        raw_data       = EXCLUDED.raw_data,
                        last_loaded_at = NOW(),
                        updated_at     = NOW()
                    RETURNING id, (xmax = 0) AS is_new
                    """,
                    (
                        item_id,
                        row.get("title"),
                        row.get("sold_date") or None,
                        row.get("sold_price") or None,
                        row.get("sold_quantity") or None,
                        raw,
                    ),
                )

            result = cur.fetchone()
            if result and result[1]:
                inserted += 1
            else:
                updated += 1

    conn.commit()
    return {"inserted": inserted, "updated": updated, "unchanged": 0}


# ---------------------------------------------------------------------------
# 4. Age calculation
# ---------------------------------------------------------------------------

def calculate_ages(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ebay_items
            SET age_in_days = CURRENT_DATE - listing_date
            WHERE listing_date IS NOT NULL
            """
        )
    conn.commit()
    log.info("age_in_days updated for all items with a listing_date")


# ---------------------------------------------------------------------------
# 5. Title word extraction
# ---------------------------------------------------------------------------

def extract_title_words(conn, run_date: date) -> None:
    stop_words = _load_stop_words()

    with conn.cursor() as cur:
        for status in ("active", "sold"):
            cur.execute(
                "SELECT title FROM ebay_items WHERE status = %s AND title IS NOT NULL",
                (status,),
            )
            titles = [row[0] for row in cur.fetchall()]

            word_counts: dict[str, int] = {}
            for title in titles:
                for word in re.findall(r"[a-z]+", title.lower()):
                    if len(word) >= 3 and word not in stop_words:
                        word_counts[word] = word_counts.get(word, 0) + 1

            for word, count in word_counts.items():
                cur.execute(
                    """
                    INSERT INTO ebay_title_words (word, status, item_count, run_date)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (word, status, run_date) DO UPDATE
                        SET item_count = EXCLUDED.item_count
                    """,
                    (word, status, count, run_date),
                )

    conn.commit()
    log.info("Title word extraction complete for run_date=%s", run_date)


# ---------------------------------------------------------------------------
# 6. Load history
# ---------------------------------------------------------------------------

def record_load(conn, filename: str, file_type: str, counts: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ebay_load_history
                (filename, file_type, rows_inserted, rows_updated, rows_unchanged)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                filename,
                file_type,
                counts["inserted"],
                counts["updated"],
                counts["unchanged"],
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_etl(filepath: str, file_type: str) -> None:
    filename = Path(filepath).name
    log.info("ETL start: %s (type=%s)", filename, file_type)

    conn = get_connection()
    try:
        if _already_loaded(conn, filename):
            log.info("Skipping %s — already recorded in load history", filename)
            return

        df = read_file(filepath, file_type)
        df = validate_and_normalize(df, file_type)

        counts = upsert_items(conn, df, file_type)
        log.info("Upsert complete: inserted=%d updated=%d", counts["inserted"], counts["updated"])

        calculate_ages(conn)
        extract_title_words(conn, date.today())
        record_load(conn, filename, file_type, counts)

        log.info("ETL complete: %s", filename)

    except Exception:
        log.exception("ETL failed for %s", filename)
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# File watcher
# ---------------------------------------------------------------------------

class _ImportHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        filename = Path(filepath).name
        if filename.startswith("."):
            return

        file_type = detect_file_type(filename)
        if file_type is None:
            log.warning(
                "Cannot determine file type for %s — filename must contain 'active' or 'sold'",
                filename,
            )
            return

        time.sleep(2)  # let the OS finish writing before we read
        run_etl(filepath, file_type)


def scan_existing_files(folder: str) -> None:
    """Process any files already in the imports folder that haven't been loaded yet."""
    conn = get_connection()
    try:
        for path in sorted(Path(folder).iterdir()):
            if path.is_dir() or path.name.startswith("."):
                continue
            file_type = detect_file_type(path.name)
            if file_type is None:
                continue
            if not _already_loaded(conn, path.name):
                log.info("Unprocessed file found on startup: %s", path.name)
                run_etl(str(path), file_type)
    finally:
        conn.close()


def watch_imports_folder() -> None:
    log.info("Watching %s with PollingObserver (60s interval)", IMPORTS_FOLDER)
    handler = _ImportHandler()
    observer = PollingObserver(timeout=60)
    observer.schedule(handler, IMPORTS_FOLDER, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
