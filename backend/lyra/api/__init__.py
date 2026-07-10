"""HTTP-слой: FastAPI-приложение, роутеры, middleware.

Только HTTP: валидация Pydantic-схемами, auth/RBAC, SSE.
Тяжёлая работа (парсинг, эмбеддинг, LLM вне графа) здесь запрещена —
см. .claude/rules/api.md и docs/architecture.md.
"""
