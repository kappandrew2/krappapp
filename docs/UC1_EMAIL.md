# UC1 — Email assistant

## Purpose

Monitor two Gmail accounts (eBay store, YouTube channel), classify incoming emails using AI and a QA pairs knowledge base, generate draft responses for human review, and send approved replies via Gmail.

---

## Schedule

Every 6 hours via APScheduler in the scheduler container.

---

## Data flow

```
Scheduler trigger (every 6 hours)
  → Pull new emails from Gmail — eBay account
  → Pull new emails from Gmail — YouTube account
  → Deduplicate against gmail_message_id in Postgres
  → For each new email:
      → AI classification (type + priority) using QA pairs
      → If priority = high → Twilio SMS to iPhone
      → AI draft response generation grounded on QA pairs
      → Save email + draft to Postgres (status = 'new')
  → Streamlit UI reflects new items
  → User reviews grid, edits draft inline, approves
  → On approval → send via Gmail API from correct account
  → Update Postgres (status = 'sent', final_reply, sent_at)
  → Override checkbox → status = 'overridden', logged to Postgres
```

---

## Email classification types

Defined in the AI classification prompt. Starting set — will evolve:

- `shipping_inquiry` — where is my item, tracking questions
- `item_specs` — questions about specifications, condition, testing
- `availability` — is this still available
- `offer_negotiation` — best offer, price questions
- `return_request` — returns, refunds, disputes
- `collaboration` — YouTube collaboration requests
- `content_question` — questions about video content
- `spam` — obvious spam
- `general` — anything else

Priority is set to `high` for: `return_request`, `dispute`, any email containing negative sentiment signals. All others default to `normal`.

---

## QA pairs knowledge base

Stored in Postgres `qa_pairs` table. Initially seeded from a manually prepared Excel file.

The AI classification and response generation prompts both receive the full active QA pairs as context. QA pairs are the grounding source — the AI uses them to match question type and draft relevant responses.

To update QA pairs: edit the source Excel and re-run the seed script, or edit directly in the database. A future enhancement may add a QA management UI tab.

---

## Streamlit UI spec

**Tab name:** Email assistant

**Filter bar (top):**
- Toggle buttons: `New` | `Replied` | `Overridden` | `All`
- Default view: `New`
- Sort: newest to oldest (received_at DESC)

**Grid columns:**

| Column | Source |
|---|---|
| Date received | `emails.received_at` |
| Account | `email_accounts.label` |
| From | `emails.from_address` |
| Type | `New email` or `Reply` based on `is_reply` |
| Subject / preview | `emails.subject` |
| Classification | `emails.classification` |
| Priority | `emails.priority` — badge: normal (gray), high (red) |
| Draft response | `emails.ai_draft` — editable text area inline |
| Approve | Button → triggers Gmail send, updates status to 'sent' |
| Override | Checkbox → marks email as handled externally, status = 'overridden' |

**Behavior:**
- Inline editing of draft response before approval
- Approve button disabled until draft has content
- Override checkbox available on any status — useful for emails handled outside the app
- Clicking a row expands the full email body

---

## External APIs and credentials

### Gmail API (OAuth 2.0)
- Two separate OAuth credential files — one per Gmail account
- Scopes required: `gmail.readonly`, `gmail.send`, `gmail.modify`
- Token files stored in `./credentials/` — persisted outside containers
- First-time OAuth flow must be run manually from terminal before scheduling begins
- Token refresh is handled automatically by the Google auth library

### Twilio SMS
- Used only for high priority email notifications
- Sends a short SMS: "High priority email from {from_address}: {subject}"
- Credentials in `.env` — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `TWILIO_TO_NUMBER`

### Anthropic Claude API
- Model: `claude-sonnet-4-5`
- Two calls per email: one for classification, one for response generation
- QA pairs passed as context in both calls
- Classification prompt returns structured JSON: `{type, priority, reasoning}`
- Response generation prompt returns plain text draft

---

## Postgres tables used

- `email_accounts` — read
- `emails` — read/write (full lifecycle)
- `qa_pairs` — read (classification and generation context)

---

## Worker module

`app/worker/jobs/email_job.py`

Key functions:
- `fetch_new_emails(account)` — calls Gmail API, returns raw message list
- `deduplicate(messages)` — filters out gmail_message_ids already in Postgres
- `classify_email(email_text, qa_pairs)` — calls Claude, returns type + priority
- `generate_draft(email_text, classification, qa_pairs)` — calls Claude, returns draft text
- `send_sms_alert(email)` — calls Twilio for high priority emails
- `save_email(email, draft)` — upserts to Postgres
- `send_reply(email_id)` — called from Streamlit on approve, sends via Gmail API, updates status

---

## Build notes for Phase 4

Dependencies to install:
```
google-auth
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
twilio
anthropic
```

Gmail OAuth first-time setup must be done interactively before the scheduler can run headlessly. Document the one-time setup steps when implementing.

The QA pairs seed script should be a standalone utility: `app/worker/scripts/seed_qa_pairs.py` — reads an Excel file and upserts into `qa_pairs`.
