-- Add sold_quantity (units per transaction from sold file) and end_date (listing expiry)
ALTER TABLE ebay_items
    ADD COLUMN IF NOT EXISTS sold_quantity INTEGER,
    ADD COLUMN IF NOT EXISTS end_date DATE;
