# Docker setup

## Prerequisites

- Docker Desktop for Mac (Apple Silicon) — latest stable
- Python 3.12 is used inside containers — no local Python required for running the app
- Git for version control

---

## docker-compose.yml spec

```yaml
version: "3.9"

networks:
  app_network:
    driver: bridge

volumes:
  postgres_data:

services:

  postgres:
    image: postgres:16-alpine
    container_name: app_postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./app/db/migrations:/docker-entrypoint-initdb.d  # runs on first start only
    networks:
      - app_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  streamlit:
    build:
      context: ./app/streamlit
      dockerfile: Dockerfile
    container_name: app_streamlit
    restart: unless-stopped
    ports:
      - "8501:8501"
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_HOST=postgres
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - EBAY_IMPORT_FOLDER=/app/imports
    volumes:
      - ./data/imports:/app/imports
      - ./credentials:/app/credentials
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - app_network

  scheduler:
    build:
      context: ./app/scheduler
      dockerfile: Dockerfile
    container_name: app_scheduler
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_HOST=postgres
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - app_network

  worker:
    build:
      context: ./app/worker
      dockerfile: Dockerfile
    container_name: app_worker
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_HOST=postgres
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}
      - TWILIO_FROM_NUMBER=${TWILIO_FROM_NUMBER}
      - TWILIO_TO_NUMBER=${TWILIO_TO_NUMBER}
      - YOUTUBE_API_KEY=${YOUTUBE_API_KEY}
      - EBAY_IMPORT_FOLDER=/app/imports
    volumes:
      - ./data/imports:/app/imports
      - ./credentials:/app/credentials
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - app_network
```

---

## Container Dockerfiles

### Base Python image (shared pattern for all Python containers)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
```

### Streamlit Dockerfile additions

```dockerfile
EXPOSE 8501
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Scheduler Dockerfile additions

```dockerfile
CMD ["python", "scheduler.py"]
```

### Worker Dockerfile additions

```dockerfile
CMD ["python", "worker.py"]
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in all values before first run.

```bash
# Database
POSTGRES_USER=appuser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=appdb

# Anthropic
ANTHROPIC_API_KEY=

# Twilio (SMS notifications)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=+1xxxxxxxxxx
TWILIO_TO_NUMBER=+1xxxxxxxxxx

# YouTube Data API v3
YOUTUBE_API_KEY=

# Gmail OAuth — paths to credential JSON files inside /app/credentials
GMAIL_EBAY_TOKEN_PATH=/app/credentials/gmail_ebay_token.json
GMAIL_YOUTUBE_TOKEN_PATH=/app/credentials/gmail_youtube_token.json

# eBay import folder (maps to container path)
EBAY_IMPORT_FOLDER=/app/imports
```

---

## Common commands

```bash
# First time setup
cp .env.example .env
# (fill in .env values)
docker compose up -d

# View logs
docker compose logs -f
docker compose logs -f worker

# Stop everything
docker compose down

# Stop and wipe database (destructive)
docker compose down -v

# Rebuild a single container after code change
docker compose build streamlit
docker compose up -d streamlit

# Open a psql shell
docker exec -it app_postgres psql -U appuser -d appdb

# Run a one-off Python script in worker context
docker compose run --rm worker python scripts/some_script.py
```

---

## Database migrations

Migrations in `app/db/migrations/` run automatically on first Postgres container start via the `docker-entrypoint-initdb.d` mount. They run in filename order.

For subsequent migrations after the database is already initialized:

```bash
docker exec -it app_postgres psql -U appuser -d appdb -f /docker-entrypoint-initdb.d/002_add_x.sql
```

Or connect via psql and run manually.

---

## Accessing the app from other devices

To access Streamlit from other devices on your home network (iPhone, iPad, other Mac):

1. Find your Mac's local IP: `ipconfig getifaddr en0`
2. On the other device, open: `http://<your-mac-ip>:8501`
3. If it doesn't connect, allow port 8501 in Mac firewall:
   - System Settings → Network → Firewall → Options → Add Docker

No other configuration needed. All data stays on your Mac.

---

## Volume and data safety

- `postgres_data` is a named Docker volume — persists across container restarts and rebuilds
- `./data/imports` is a bind mount — files you drop here are visible inside containers immediately
- `./credentials` is a bind mount — OAuth tokens stored here persist outside containers
- To back up the database: `docker exec app_postgres pg_dump -U appuser appdb > backup.sql`
- Never run `docker compose down -v` unless you intend to wipe the database
