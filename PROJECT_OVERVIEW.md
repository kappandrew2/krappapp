# Project overview

## What this is

A personal productivity platform for managing an eBay vintage audio store and YouTube channel. Built as a set of Docker containers running locally on a MacBook Air M4. All use cases share a single Postgres database and surface through a multi-tab Streamlit application.

The system is designed to run unattended on a schedule, presenting AI-assisted insights and action queues for human review. Nothing executes without explicit approval in the UI — the AI prepares, the human decides.

---

## Tech stack

| Layer | Technology |
|---|---|
| Runtime | Docker Desktop (Apple Silicon / ARM) |
| Orchestration | Docker Compose |
| Database | PostgreSQL 16 |
| Application UI | Streamlit (Python 3.12) |
| Scheduling | APScheduler (inside scheduler container) |
| AI | Anthropic Claude API (claude-sonnet-4-5) |
| Notifications | Twilio SMS |
| Email | Gmail API (OAuth 2.0) |
| YouTube | YouTube Data API v3 |
| Language | Python 3.12 throughout |

---

## Container map

```
docker-compose.yml
├── postgres          # PostgreSQL 16, persistent volume
├── streamlit         # Streamlit app, all tabs, port 8501
├── scheduler         # APScheduler, triggers jobs on cadence
└── worker            # Executes job logic when triggered by scheduler
```

All containers communicate over a single Docker bridge network (`app_network`). No container is exposed to the internet. The Streamlit UI is accessible at `http://localhost:8501` and optionally on the local network via Mac firewall rule on port 8501.

---

## Shared infrastructure

### Environment variables
All secrets and config live in a `.env` file at the project root. Never committed to git.

```
ANTHROPIC_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
TWILIO_TO_NUMBER=
GMAIL_EBAY_CREDENTIALS=      # path to OAuth JSON
GMAIL_YOUTUBE_CREDENTIALS=   # path to OAuth JSON
YOUTUBE_API_KEY=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=appdb
EBAY_IMPORT_FOLDER=          # local path watched for CSV drops
```

### Volume mounts
```
./data/postgres     → /var/lib/postgresql/data   (database persistence)
./data/imports      → /app/imports               (eBay CSV drop folder)
./credentials       → /app/credentials           (OAuth JSON files)
```

---

## Streamlit tab structure

| Tab | Use case |
|---|---|
| Email assistant | Gmail inbox management, AI draft responses |
| YouTube monitor | Comment sentiment, offensive comment review |
| eBay inventory | Inventory ETL, listing age analysis, word trends |
| Research — strategy | Weekly AI content research, video ideas |
| Research — chatter | Community buzz digest for filming reference |

---

## Build phases

| Phase | Scope | Proves |
|---|---|---|
| 1 | Postgres + Docker Compose + Streamlit shell | Container network, data layer, UI skeleton |
| 2 | eBay inventory tab | File-triggered ETL → Postgres → UI end to end |
| 3 | YouTube comment monitor | Scheduler container, YouTube API, AI classification |
| 4 | Email assistant | Gmail OAuth, Twilio SMS, AI draft generation |
| 5 | Research agent | Web scraping, multi-source AI synthesis |

Each phase must be fully functional and tested before the next begins.

---

## Repository structure

```
/
├── docker-compose.yml
├── .env                        # secrets — never commit
├── .env.example                # committed template with blank values
├── docs/
│   ├── PROJECT_OVERVIEW.md
│   ├── DATA_MODEL.md
│   ├── DOCKER_SETUP.md
│   ├── BUILD_LOG.md
│   └── use_cases/
│       ├── UC1_EMAIL.md
│       ├── UC2_YOUTUBE.md
│       ├── UC3_EBAY.md
│       └── UC4_RESEARCH.md
├── app/
│   ├── streamlit/              # Streamlit pages and components
│   ├── scheduler/              # APScheduler setup
│   ├── worker/                 # Job logic modules
│   ├── db/                     # Database connection, migrations
│   └── shared/                 # Shared utilities (AI client, logger)
├── data/
│   ├── postgres/               # Postgres volume (gitignored)
│   └── imports/                # eBay CSV drop folder (gitignored)
└── credentials/                # OAuth JSON files (gitignored)
```
