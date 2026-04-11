"""Configuration for Tracebow agent and services."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict()

    # LLM (Ollama) — dual-model strategy
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_model_rca: str = "phi4-mini"

    # Vector DB (ChromaDB)
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "tracebow_embeddings"

    # Graph DB
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"

    # Message broker (RabbitMQ)
    rabbitmq_url: str = "amqp://tracebow:tracebow@rabbitmq:5672//"

    # Result backend + cache (Redis)
    redis_url: str = "redis://redis:6379/0"

    # Celery worker tuning
    celery_worker_concurrency: int = 4
    celery_rca_rate_limit: str = "10/m"
    celery_task_result_ttl: int = 86400

    # Integrations (optional)
    jenkins_url: str = ""
    jenkins_api_token: str = ""
    jenkins_user: str = ""

    github_token: str = ""
    github_webhook_secret: str = ""

    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # API (bind all interfaces — expected inside Docker)
    api_host: str = "0.0.0.0"  # nosec B104
    api_port: int = 8080
    cors_origins: list[str] = ["*"]

    # Embedding model (for Ollama)
    embedding_model: str = "nomic-embed-text"


def get_settings() -> Settings:
    """Return settings singleton."""
    return settings


settings = Settings()
