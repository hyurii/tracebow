"""
Celery application — RabbitMQ broker, Redis result backend.

Worker command (run from the agent image):
    celery -A tracebow.celery_app worker -l info -Q rca,default
Beat (periodic scheduler):
    celery -A tracebow.celery_app beat -l info
Flower (monitoring):
    celery -A tracebow.celery_app flower --port=5555
"""

from celery import Celery
from celery.schedules import crontab

from tracebow.config import settings

app = Celery("tracebow")

app.conf.update(
    broker_url=settings.rabbitmq_url,
    result_backend=settings.redis_url,
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Reliability — re-deliver if worker crashes mid-task
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Backpressure — one task at a time per worker process (LLM is the bottleneck)
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=200,
    # Results
    result_expires=settings.celery_task_result_ttl,
    # Queue routing
    task_default_queue="default",
    task_routes={
        "tracebow.tasks.run_rca": {"queue": "rca"},
        "tracebow.tasks.run_jenkins_rca": {"queue": "rca"},
        "tracebow.tasks.run_github_rca": {"queue": "rca"},
        "tracebow.tasks.run_cli_rca": {"queue": "rca"},
        "tracebow.tasks.cleanup_stale_results": {"queue": "maintenance"},
        "tracebow.tasks.health_check_ollama": {"queue": "maintenance"},
        "tracebow.tasks.cleanup_embedding_cache": {"queue": "maintenance"},
    },
    # RabbitMQ priority queues (0-9, higher = more urgent)
    task_queue_max_priority=10,
    task_default_priority=5,
    # Autodiscover task modules
    include=["tracebow.tasks"],
    # Beat schedule — periodic maintenance
    beat_schedule={
        "health-check-ollama": {
            "task": "tracebow.tasks.health_check_ollama",
            "schedule": 300.0,  # every 5 minutes
        },
        "cleanup-stale-results": {
            "task": "tracebow.tasks.cleanup_stale_results",
            "schedule": crontab(minute=0, hour="*/6"),  # every 6 hours
        },
        "cleanup-embedding-cache": {
            "task": "tracebow.tasks.cleanup_embedding_cache",
            "schedule": crontab(minute=30, hour=3),  # daily at 03:30 UTC
        },
    },
)
