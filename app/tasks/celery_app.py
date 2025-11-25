import os
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

BROKER_URL = settings.BROKER_URL
RESULT_BACKEND = settings.RESULT_BACKEND

celery_app = Celery(
    "email_tasks",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.tasks.emailer", "app.tasks.schedulers"]  
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=int(os.environ.get("CELERY_PREFETCH_MULTIPLIER", "1")),
    worker_concurrency=int(os.environ.get("CELERY_CONCURRENCY", "4")),
    task_time_limit=int(os.environ.get("CELERY_TASK_TIME_LIMIT", 60 * 5)),
    task_soft_time_limit=int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", 60 * 4)),
    result_expires=60 * 60 * 24,
    broker_pool_limit=int(os.environ.get("BROKER_POOL_LIMIT", "10")),
    timezone="UTC",
)

celery_app.conf.beat_schedule = {
    "enqueue-due-campaigns-every-50-seconds": {
        "task": "app.tasks.schedulers.enqueue_due_campaigns",  
        "schedule": settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS,   
         "options": {"queue": "control"} },
}
