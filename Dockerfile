FROM python:3.12-slim

WORKDIR /app

# System deps (if you need gcc, etc., add here)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy code
COPY . /app

# Install Python deps
# If you have requirements.txt, adjust path
RUN pip install --no-cache-dir -r requirements.txt

# Environment defaults (can be overridden in compose)
ENV APP_ENV=production \
    DATABASE_URL=sqlite:///./data/app.db \
    REPORTS_DIR=./data/reports \
    RESULT_BACKEND=redis://redis:6379/0 \
    BROKER_URL=redis://redis:6379/0 \
    SMTP_HOST=mailhog \
    SMTP_PORT=1025 \
    SMTP_USER= \
    SMTP_PASSWORD= \
    SMTP_USE_TLS=false

# Ensure data dir exists
RUN mkdir -p /app/data/reports

# Default command (overridden per service in docker-compose)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]