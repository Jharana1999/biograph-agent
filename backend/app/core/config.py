from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Biomedical Research Agent"
    api_prefix: str = "/api"

    # LLM
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"

    # Postgres
    postgres_dsn: str = "postgresql+asyncpg://agent:agent@localhost:5432/agent_llm"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpass"

    # API timeouts
    http_timeout_s: float = 30.0

    # Frontend origin(s) allowed by CORS. Comma-separated.
    cors_origins: str = "http://localhost:4200"

    @property
    def cors_origins_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()

