"""
Celery application — Redis broker AND result backend.

We dropped RabbitMQ + Flower because:
- Redis-as-broker handles tens of tasks/minute (our workload) without issue.
- One fewer container, ~400 MB RAM, less ops surface.
- The backpressure we care about (protect Ollama) is enforced by
  `rate_limit` + `worker_prefetch_multiplier=1`, not by the broker.

Worker command (run from the agent image):
    celery -A tracebow.celery_app worker -l info -Q rca,default,maintenance
Beat (periodic scheduler):
    celery -A tracebow.celery_app beat -l info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from tracebow.config import settings

app = Celery("tracebow")

app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Re-deliver if a worker crashes mid-task. With Redis brokers this
    # relies on visibility_timeout, which defaults to 1h — fine for us.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # The LLM (Ollama) is the bottleneck: one task in flight per process.
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=200,
    result_expires=settings.celery_task_result_ttl,
    task_default_queue="default",
    task_routes={
        "tracebow.tasks.run_rca": {"queue": "rca"},
        "tracebow.tasks.run_jenkins_rca": {"queue": "rca"},
        "tracebow.tasks.run_github_rca": {"queue": "rca"},
        "tracebow.tasks.run_cli_rca": {"queue": "rca"},
        "tracebow.tasks.run_chat": {"queue": "rca"},
        "tracebow.tasks.health_check_ollama": {"queue": "maintenance"},
        "tracebow.tasks.cleanup_stale_results": {"queue": "maintenance"},
        "tracebow.tasks.backup_wiki": {"queue": "maintenance"},
    },
    include=["tracebow.tasks"],
    beat_schedule={
        "health-check-ollama": {
            "task": "tracebow.tasks.health_check_ollama",
            "schedule": 300.0,
        },
        "cleanup-stale-results": {
            "task": "tracebow.tasks.cleanup_stale_results",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "backup-wiki": {
            "task": "tracebow.tasks.backup_wiki",
            "schedule": crontab(minute=15, hour="*"),  # hourly; task self-checks cadence
        },
    },
)
