import os
from celery import Celery

BROKER_URL = os.environ.get("BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.environ.get("RESULT_BACKEND", BROKER_URL)

celery_app = Celery(
    "email_tasks",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.tasks.emailer", "app.tasks.schedulers"]  # match actual module paths
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
    "enqueue-due-campaigns-every-10-seconds": {
        "task": "app.tasks.schedulers.enqueue_due_campaigns",  # match the @task name
        "schedule": 50.0   ,
         "options": {"queue": "control"} },
}
