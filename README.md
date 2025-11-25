#  Email Campaign Service

A bulk‑email campaign system built with **FastAPI**, **SQLAlchemy**, **Celery**, and **Redis**.

---

##  Features
- Upload recipients from CSV
- Create & schedule campaigns
- Background email sending via Celery workers
- Track delivery logs & errors
- Generate CSV reports and email summaries

---

##  Configuration
Settings are managed in `config.py` and `.env`.

Key environment variables:
- `DATABASE_URL`: DB connection (SQLite by default, swap to Postgres/MySQL for production)
- `ADMIN_EMAIL`: where campaign summaries + reports are sent
- `SMTP_*`: SMTP server details (MailHog for dev, real SMTP in prod)
- `BROKER_URL` / `RESULT_BACKEND`: Redis connection for Celery
- `REPORTS_DIR`: directory for CSV reports

---

##  Clone the repo

 - git clone https://github.com/anandpadmanabhan1997/email_campaign.git
 - cd email_campaign
 - git checkout main


##  Setup --> Local vs Docker

##  Local Setup

### 1. Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

### 2. Run services
Redis:
docker run -p 6379:6379 -d redis:7-alpine

MailHog:
docker run -p 1025:1025 -p 8025:8025 -d mailhog/mailhog:v1.0.1

### 3. Start FastAPI
uvicorn app.main:app --reload --port 8000

App: http://localhost:8000  
Docs: http://localhost:8000/docs

### 4. Run Celery workers
celery -A app.tasks.celery_app:celery_app worker -B -l info -Q control,send
celery -A app.tasks.celery_app:celery_app worker -l info -Q celery,monitor

---

##  Docker Compose

This repo includes `docker-compose.yml` to run everything in containers:

- web: FastAPI + Uvicorn
- worker_send: Celery worker (queues control,send + beat)
- worker_monitor: Celery worker (queues celery,monitor)
- redis: broker / result backend
- mailhog: dev SMTP + web UI

Start with:
docker compose up --build

Then:
- App: http://localhost:8000
- MailHog: http://localhost:8025

---

##  Usage

- Recipients page: upload CSV (`email,name,subscription_status`)
- Campaigns page: create draft campaigns, optionally schedule
- Scheduler: moves drafts to scheduled, enqueues send tasks
- Workers: send emails, monitor progress, finalize campaigns
- Reports: CSV saved to `REPORTS_DIR` + emailed to `ADMIN_EMAIL`

---

##  Notes
- SQLite is fine for dev; use Postgres/MySQL for production.
- All settings centralized in `config.py`.
- Reports must be saved to a writable directory (`./data/reports` locally).

---

