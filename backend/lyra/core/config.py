"""Конфигурация приложения: только через pydantic-settings, env-префикс LYRA_."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LYRA_", env_file=".env", extra="ignore")

    env: str = "dev"

    # Auth (используется с фазы 1)
    jwt_secret: str = "change-me"
    admin_email: str = "admin@lyra.local"
    admin_password: str = "change-me"

    # PostgreSQL
    db_host: str = "postgres"
    db_port: int = 5432
    db_user: str = "lyra"
    db_password: str = "lyra"
    db_name: str = "lyra"

    # Инфраструктурные сервисы (дефолты = хосты docker-compose)
    redis_url: str = "redis://redis:6379/0"
    ollama_url: str = "http://ollama:11434"
    embeddings_url: str = "http://embeddings:80"
    reranker_url: str = "http://reranker:80"

    # Retrieval (фаза 3). Дефолты — для CPU-стенда (замерено: cross-encoder
    # bge-reranker-v2-m3 на CPU ~0.3-0.5с/пару при 400-600 символах текста;
    # 50 пар x 512 токенов из ADR-004 реалистичны только на GPU — там
    # поднять top_n/max_chars и вернуть timeout 3с)
    reranker_timeout_s: float = 15.0
    rerank_top_n: int = 12  # кандидатов после RRF отправляется в reranker
    rerank_text_max_chars: int = 600  # обрезка текста для скоринга (chunk не трогается)

    # Ingest (фаза 2)
    upload_dir: str = "/data/uploads"
    upload_max_bytes: int = 50 * 1024 * 1024  # FR-1
    embedding_batch_size: int = 16
    # Токенайзер bge-m3 из HF-кэша (volume hf_cache, общий с TEI)
    hf_cache_dir: str = "/data/hf"
    tokenizer_model: str = "BAAI/bge-m3"

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
