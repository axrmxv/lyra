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

    # RAG-граф (фаза 4, ADR-006/007/009)
    generation_model: str = "qwen2.5:7b-instruct-q4_K_M"
    grading_model: str = "qwen2.5:7b-instruct-q4_K_M"  # grading можно перевести на меньшую
    llm_timeout_s: float = 300.0  # CPU: prompt eval ~1мин + генерация ~5-15 ток/c
    # KV-кэш Ollama пропорционален num_ctx; дефолт модели (32k) выедает память
    # CPU-стенда (OOM embeddings). 16k = рабочий лимит context-management §2
    llm_num_ctx: int = 16384
    rag_top_k: int = 8  # chunks в контекст генерации (context-management §2)
    # Эвристики grade_sufficiency до LLM-judge (ADR-006)
    sufficiency_min_candidates: int = 3
    sufficiency_min_rerank_score: float = 0.02
    # Верхняя эвристика: cross-encoder уверен (score ≥ порога) → sufficient
    # без LLM-judge. Точнее капризов 7B-судьи и экономит 40-50с CPU-вызова
    sufficiency_auto_accept_score: float = 0.6
    # Бюджеты контекста в токенах (context-management §2; приближение
    # токенайзером bge-m3 — chunks несут token_count)
    ctx_budget_system: int = 1000
    ctx_budget_history: int = 2000
    ctx_budget_chunks: int = 8000
    # 800 вместо 2000 из context-management §2: фактические ответы ~100-300
    # токенов, а на CPU каждый токен ~0.1-0.2с — верхняя граница бережёт p95
    ctx_budget_completion: int = 800

    # Chat API (фаза 5): rate limiting и очередь к Ollama (nfr §2,
    # security-and-access §7 — защита локальной LLM от случайного DoS)
    rate_limit_chat_per_minute: int = 10
    rate_limit_login_per_minute: int = 5
    llm_max_concurrency: int = 2  # одновременных генераций; переполнение → 429
    llm_overload_retry_after_s: int = 30  # Retry-After при занятом семафоре
    chat_history_messages: int = 10  # хвост истории сессии в контекст графа
    cors_origins: str = "http://localhost:5173"  # origin фронтенда, через запятую

    # Evals (фаза 6). Judge только в evals/CI, в runtime не используется
    # (eval-plan §1, A-9). local = Ollama (на GPU ставить qwen2.5:14b);
    # cloud = OpenAI-совместимый endpoint, ключ из env — только для CI.
    judge_provider: str = "local"  # local | cloud
    judge_model: str = "qwen2.5:7b-instruct-q4_K_M"  # локальный судья (CPU-стенд)
    judge_api_base: str = ""  # например https://api.openai.com/v1
    judge_api_key: str = ""  # секрет: env LYRA_JUDGE_API_KEY / GitHub Secrets
    judge_cloud_model: str = "gpt-4o-mini"
    judge_timeout_s: float = 120.0
    # Каталог evals/ (датасет, thresholds, baseline, отчёты); в контейнерах
    # монтируется в /repo/evals
    evals_dir: str = "evals"

    # Ingest (фаза 2)
    upload_dir: str = "/data/uploads"
    upload_max_bytes: int = 50 * 1024 * 1024  # FR-1
    embedding_batch_size: int = 16
    # Токенайзер bge-m3 из HF-кэша (volume hf_cache, общий с TEI)
    hf_cache_dir: str = "/data/hf"
    tokenizer_model: str = "BAAI/bge-m3"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
