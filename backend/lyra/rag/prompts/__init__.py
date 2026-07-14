"""Загрузчик промптов: только файлы *.md, версия (sha256[:8]) — в трейс
и eval_runs.config_snapshot. Инлайн-промптов в коде не бывает
(.claude/rules/rag-core.md).
"""

import hashlib
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> tuple[str, str]:
    """(текст, версия). Версия — хэш содержимого: меняется вместе с файлом."""
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    version = hashlib.sha256(text.encode()).hexdigest()[:8]
    return text, version


def prompt_versions() -> dict[str, str]:
    """Все версии промптов — для config_snapshot eval-прогонов (фаза 6)."""
    return {path.stem: load_prompt(path.stem)[1] for path in sorted(_PROMPTS_DIR.glob("*.md"))}
