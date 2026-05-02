# UC3 — eBay inventory monitor

## Purpose

Track active listings and sold items from the eBay store. Provides visibility into listing age, category performance, and title word trends. Helps identify long-listed items consuming physical space and understand what content/items perform well over time.

---

## Schedule

File-triggered. The worker watches `./data/imports/` for new CSV or Excel files. When a new file is detected, ETL runs automatically. No fixed time schedule.

---

## File drop process

1. Export active listings from eBay Seller Hub as CSV or Excel
2. Export sold listings from eBay Seller Hub as CSV or Excel
3. Drop both files into the watched folder (`./data/imports/`)
4. App detects new files and runs ETL automatically
5. A clickable link in the Streamlit UI opens the imports folder in Finder

Files can be dropped at any time — weekly is the intended cadence.

---

## ETL logic

### File detection
Worker polls the imports folder every 5 minutes. Detects files not yet recorded in `ebay_load_history`. Processes active listings file first, then sold listings file.

File naming convention (to distinguish type):
- Active listings file must contain `active` in the filename
- Sold listings file must contain `sold` in the filename

Example: `active_listings_2025_05_01.csv`, `sold_listings_2025_05_01.csv`

### Validation and normalization
- Confirm required columns exist: item ID, title, listing date
- Parse dates to standard format
- Coerce numeric columns (price, etc.)
- Strip whitespace from text fields
- Map eBay column names to internal schema names (mapping defined in config, updated as needed)

### Upsert logic (applied per row, keyed on `ebay_item_id`)

```
IF item_id NOT in ebay_items:
    INSERT new row
    Set listing_date from file (never overwrite after first insert)
    Set status from file type ('active' or 'sold')

ELSE:
    UPDATE all columns EXCEPT listing_date
    If file type is 'sold' and current status is 'active':
        Set status = 'sold'
        Set sold_date from file
    Update updated_at timestamp
```

### Age calculation
After upsert, calculate `age_in_days` for all items:
```sql
UPDATE ebay_items
SET age_in_days = CURRENT_DATE - listing_date
WHERE listing_date IS NOT NULL;
```

### Title word extraction
After each ETL run, rebuild the word frequency table for `run_date = today`:

1. Fetch all item titles (active and sold separately)
2. Tokenize: lowercase, split on whitespace and punctuation
3. Remove stop words (standard English stop word list: the, a, an, for, in, of, with, etc.)
4. Remove very short words (< 3 characters)
5. Count word frequency per status
6. Upsert into `ebay_title_words` (word, status, item_count, run_date)

### Load history
Record every file load in `ebay_load_history` with row counts.

---

## Streamlit UI spec

**Tab name:** eBay inventory

**Folder link:**
A button at the top of the tab opens the imports folder in Finder using `subprocess.run(['open', folder_path])`. Label: "Open imports folder"

**Summary bar:**
Four stat tiles at the top:

| Stat | Calculation |
|---|---|
| Active listings | COUNT WHERE status = 'active' |
| Sold (last 12 months) | COUNT WHERE status = 'sold' AND sold_date >= 1 year ago |
| Long-listed | COUNT WHERE status = 'active' AND age_in_days >= 365 |
| Last loaded | MAX(loaded_at) from ebay_load_history |

**Filter bar:**
- Toggle: `All` | `Active` | `Sold`
- Default: `Active`

**Main grid:**

| Column | Source | Notes |
|---|---|---|
| Item ID | `ebay_item_id` | |
| Title | `title` | |
| Category | `category` | filterable dropdown |
| Status | `status` | badge: active (green), sold (gray) |
| Listed | `listing_date` | |
| Sold date | `sold_date` | blank if active |
| Age (days) | `age_in_days` | sortable — default sort descending |
| Price | `price` | |
| Sold price | `sold_price` | blank if active |

All columns sortable. Category and status filterable. Search box for title keyword filter.

**Word frequency section (below grid):**

- Date range slider: select start and end date
- Toggle: `Active items` | `Sold items` | `Both`
- Bar chart: top 20 words by frequency within selected date range and status
- Updates dynamically as slider moves

---

## Postgres tables used

- `ebay_items` — read/write (upsert on every load)
- `ebay_title_words` — read/write (rebuilt on each ETL run)
- `ebay_load_history` — write (audit log per load)

---

## Worker module

`app/worker/jobs/ebay_etl_job.py`

Key functions:
- `watch_imports_folder()` — polls for new files, triggers ETL
- `detect_file_type(filename)` — returns 'active' or 'sold' based on filename
- `validate_and_normalize(df)` — cleans and maps columns
- `upsert_items(df, file_type)` — runs upsert logic, returns row counts
- `calculate_ages()` — updates age_in_days for all items
- `extract_title_words(run_date)` — builds word frequency for today
- `record_load(filename, file_type, counts)` — writes to load_history

---

## Column mapping config

eBay export column names will be discovered during first build. A config file maps eBay column names to internal schema names:

`app/worker/config/ebay_column_map.json`

```json
{
  "Item number": "ebay_item_id",
  "Title": "title",
  "Start date": "listing_date",
  "Sold date": "sold_date",
  "Sold for": "sold_price",
  "Current price": "price",
  "Category": "category"
}
```

This file is updated as actual eBay export column names are confirmed during Phase 2 build.

---

## Build notes for Phase 2

This is the first feature built after Phase 1 foundation. Build in this order:

1. File watcher — prove it detects a dropped file
2. CSV parse + validate — prove it reads an actual eBay export
3. Upsert logic — prove create and update paths work correctly
4. Age calculation — prove it runs after each load
5. Word extraction — prove it builds the frequency table
6. Streamlit tab — grid, summary bar, word chart
7. Folder link button

Start with a small real export from eBay Seller Hub as test data. Confirm column names match the mapping config and adjust as needed.

Dependencies to install:
```
pandas
openpyxl
watchdog
sqlalchemy
psycopg2-binary
streamlit
plotly
```

The `watchdog` library handles file system monitoring cleanly on macOS.
