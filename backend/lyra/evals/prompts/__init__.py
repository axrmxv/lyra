"""Загрузчик judge-промптов: только файлы *.md, версия (sha256[:8])
попадает в config_snapshot run'а (.claude/rules/evals.md)."""

import hashlib
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_judge_prompt(name: str) -> tuple[str, str]:
    """(текст, версия). Версия — хэш содержимого: меняется вместе с файлом."""
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    version = hashlib.sha256(text.encode()).hexdigest()[:8]
    return text, version


def judge_prompt_versions() -> dict[str, str]:
    return {
        path.stem: load_judge_prompt(path.stem)[1] for path in sorted(_PROMPTS_DIR.glob("*.md"))
    }
