"""Configuration for Tracebow agent and services."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # LLM (Ollama) — dual-model strategy
    ollama_base_url: str = "http://ollama:11434"
    # General chat, Jira/Slack-style RAG summarization (fast)
    ollama_model: str = "llama3.2:3b"
    # Deep coding, stack traces, CI RCA (Jenkins/GitHub webhooks & sync RCA)
    ollama_model_rca: str = "phi4-mini"

    # Vector DB
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "tracebow_embeddings"

    # Graph DB
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"

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

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: list[str] = ["*"]

    # Embedding model (for Ollama)
    embedding_model: str = "nomic-embed-text"


def get_settings() -> Settings:
    """Return settings singleton."""
    return settings


settings = Settings()
