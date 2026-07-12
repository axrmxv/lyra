"""Подсчёт токенов токенайзером embedding-модели (bge-m3) — ADR-002.

Размеры chunks считаются токенами модели, не символами: русский текст
токенизируется плотнее. Файл tokenizer.json берётся из HF-кэша (volume
hf_cache, общий с TEI) — офлайн; при отсутствии скачивается один раз.
"""

from functools import lru_cache

from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from lyra.core.config import get_settings


@lru_cache
def get_tokenizer() -> Tokenizer:
    settings = get_settings()
    path = hf_hub_download(
        settings.tokenizer_model,
        "tokenizer.json",
        cache_dir=settings.hf_cache_dir,
    )
    return Tokenizer.from_file(path)


def count_tokens(text: str) -> int:
    return len(get_tokenizer().encode(text, add_special_tokens=False).ids)
