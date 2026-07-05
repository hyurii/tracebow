"""Configuration for Tracebow agent and services."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    # ------------------------------------------------------------------
    # LLM (Ollama) — dual-model strategy. LLM is optional: if the host is
    # unreachable or OLLAMA_ENABLED=false, the LangGraph "reason" node
    # falls back to a deterministic templated summary.
    # ------------------------------------------------------------------
    ollama_enabled: bool = True
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_model_rca: str = "phi4-mini"
    # CPU inference is slow, so give it a generous per-request budget.
    ollama_request_timeout: int = 120
    ollama_temperature: float = 0.1
    # Upper bound on ReAct tool-calling rounds in the reason node.
    reason_max_tool_iterations: int = 4

    # ------------------------------------------------------------------
    # Task queue (Celery on Redis — Redis is broker AND result backend).
    # RabbitMQ has been removed.
    # ------------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = ""
    celery_worker_concurrency: int = 4
    celery_rca_rate_limit: str = "10/m"
    celery_task_result_ttl: int = 86400  # 24h

    # ------------------------------------------------------------------
    # Telemetry database. Postgres in production (docker-compose); tests
    # and CLI use SQLite via DATABASE_URL=sqlite+aiosqlite:///...
    # ------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://tracebow:tracebow@postgres:5432/tracebow"

    # ------------------------------------------------------------------
    # Git-backed Markdown wiki. Path is a persistent volume inside the
    # container; "git init" runs idempotently on startup.
    # ------------------------------------------------------------------
    wiki_path: str = "/wiki"
    wiki_default_branch: str = "main"
    wiki_author_name: str = "Tracebow Agent"
    wiki_author_email: str = "tracebow-agent@localhost"
    # Master key used to encrypt deploy keys stored in the DB. Defaults
    # to a dev value; PRODUCTION OPERATORS MUST OVERRIDE THIS.
    wiki_secret_key: str = "tracebow-dev-unsafe-key-please-override"

    # ------------------------------------------------------------------
    # Integrations (optional; tools return "not configured" otherwise).
    # ------------------------------------------------------------------
    jenkins_url: str = ""
    jenkins_api_token: str = ""
    jenkins_user: str = ""

    github_token: str = ""
    github_api_base: str = "https://api.github.com"
    github_webhook_secret: str = ""

    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # ------------------------------------------------------------------
    # API. Host 0.0.0.0 is expected inside Docker.
    # ------------------------------------------------------------------
    api_host: str = "0.0.0.0"  # nosec B104
    api_port: int = 8080
    cors_origins: list[str] = ["*"]

    def model_post_init(self, _: object) -> None:
        # Default Celery broker to the shared Redis URL when not overridden.
        if not self.celery_broker_url:
            object.__setattr__(self, "celery_broker_url", self.redis_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings singleton (cached per process)."""
    return Settings()


class _SettingsProxy:
    """Backwards-compatible proxy so ``from tracebow.config import settings`` still works.

    Attribute access always delegates to the cached settings object, so
    tests that mutate env + call ``get_settings.cache_clear()`` still see
    fresh values through either entry point.
    """

    def __getattr__(self, name: str) -> object:
        return getattr(get_settings(), name)

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(get_settings(), name, value)


settings: Settings = _SettingsProxy()  # type: ignore[assignment]
