"""
seed_qa_pairs.py — Seed the qa_pairs table with starting QA pairs for the
eBay vintage audio store and YouTube channel email assistant.

Idempotent: uses ON CONFLICT DO NOTHING on (question) — safe to run multiple
times without creating duplicates.

Run inside the scheduler container:
    docker exec -it app_scheduler python scripts/seed_qa_pairs.py
"""

import logging
import os
import sys

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

QA_PAIRS = [
    {
        "question": "How long does shipping take?",
        "answer": (
            "I ship within 1 business day of payment. Domestic packages arrive in "
            "2–5 business days via USPS Priority Mail or UPS Ground depending on "
            "your location. I provide tracking as soon as the label is created."
        ),
        "tags": ["shipping", "timeframe"],
    },
    {
        "question": "What is the condition of this item?",
        "answer": (
            "All items are accurately described in the listing. I test every piece "
            "of audio equipment for basic functionality before listing. Cosmetic "
            "flaws are noted and photographed. If you have specific condition "
            "questions about an item, please message me with the item number."
        ),
        "tags": ["condition", "testing"],
    },
    {
        "question": "What is your return policy?",
        "answer": (
            "I accept returns within 30 days of delivery for items that are "
            "significantly not as described. Buyer pays return shipping unless the "
            "item arrived damaged or was misrepresented. Please message me before "
            "opening a return case — I always work to resolve issues directly."
        ),
        "tags": ["returns", "policy"],
    },
    {
        "question": "Do you offer combined shipping?",
        "answer": (
            "Yes, I'm happy to combine shipping on multiple items. Purchase all "
            "the items you want and message me before paying — I'll send a revised "
            "invoice with the combined shipping discount applied."
        ),
        "tags": ["shipping", "combined", "discount"],
    },
    {
        "question": "Has this item been tested?",
        "answer": (
            "Yes. All electronics are powered on and tested for basic functionality "
            "before listing. Turntables are tested for motor function and speed. "
            "Amplifiers and receivers are tested for audio output on all channels. "
            "Any faults found during testing are disclosed in the listing."
        ),
        "tags": ["testing", "functionality", "condition"],
    },
    {
        "question": "Is this a complete unit or sold for parts?",
        "answer": (
            "The listing title and description specify whether an item is sold as "
            "fully functional, as-is for repair, or for parts only. Items listed "
            "'for parts' are not guaranteed to power on or function and are priced "
            "accordingly. Please read the full listing description carefully."
        ),
        "tags": ["parts", "complete", "condition"],
    },
    {
        "question": "Do you ship internationally?",
        "answer": (
            "I ship to most countries via USPS First Class International or "
            "Priority Mail International. Shipping costs and delivery times vary "
            "by destination. Buyer is responsible for any import duties or customs "
            "fees. Some fragile or heavy items may be domestic-only due to "
            "shipping risk — check the listing for international availability."
        ),
        "tags": ["shipping", "international"],
    },
    {
        "question": "What payment methods do you accept?",
        "answer": (
            "I accept all payment methods supported by eBay, including PayPal, "
            "credit cards, Apple Pay, and Google Pay. Payment is due within "
            "4 days of purchase per eBay policy. If you need more time, please "
            "message me before the deadline."
        ),
        "tags": ["payment"],
    },
    {
        "question": "Will you accept a lower offer or best offer?",
        "answer": (
            "My prices are researched and fair for the condition. If the listing "
            "has Best Offer enabled, please use the eBay Best Offer feature to "
            "submit your offer and I will respond promptly. For fixed-price "
            "listings I may consider reasonable offers — feel free to message me."
        ),
        "tags": ["offer", "negotiation", "price"],
    },
    {
        "question": "Is local pickup available?",
        "answer": (
            "Local pickup may be available for select large or heavy items. "
            "If the listing offers local pickup, you can select that option at "
            "checkout. For items not listed with local pickup, please message me "
            "to discuss — I'm located in the greater Portland, Oregon area."
        ),
        "tags": ["pickup", "local"],
    },
]


def seed(conn) -> None:
    inserted = 0
    skipped = 0

    with conn.cursor() as cur:
        for pair in QA_PAIRS:
            cur.execute(
                """
                INSERT INTO qa_pairs (question, answer, tags, active, created_at, updated_at)
                VALUES (%s, %s, %s, TRUE, NOW(), NOW())
                ON CONFLICT DO NOTHING
                """,
                (pair["question"], pair["answer"], pair["tags"]),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1

    conn.commit()
    log.info("QA pairs: %d inserted, %d already existed (skipped)", inserted, skipped)


def main() -> None:
    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    try:
        seed(conn)
    finally:
        conn.close()
    log.info("Seed complete")


if __name__ == "__main__":
    main()
