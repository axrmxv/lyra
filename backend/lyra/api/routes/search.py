"""POST /search — raw retrieval без генерации (docs/api-contract.md §3, UC-9)."""

from fastapi import APIRouter, Depends

from lyra.api.deps import require_role
from lyra.api.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import UserRole
from lyra.db.session import get_sessionmaker
from lyra.retrieval.interfaces import SearchFilters
from lyra.retrieval.retriever import HybridRetriever

router = APIRouter(tags=["search"])


@router.post("/search", dependencies=[Depends(require_role(UserRole.VIEWER))])
async def search(body: SearchRequest) -> SearchResponse:
    # Retriever получает фабрику сессий: каналы выполняются параллельно,
    # каждому нужна собственная сессия (ADR-005)
    retriever = HybridRetriever(get_sessionmaker(), get_settings())
    result = await retriever.retrieve(
        body.query,
        tenant_id=DEFAULT_TENANT_ID,
        filters=SearchFilters(
            collection_id=body.collection_id,
            source_id=body.filters.source_id,
            source_type=tuple(body.filters.source_type),
            lang=body.filters.lang,
        ),
        top_k=body.top_k,
        rerank=body.rerank,
    )
    return SearchResponse(
        results=[SearchResultItem.from_chunk(chunk) for chunk in result.chunks],
        degraded=result.degraded,
        took_ms=result.took_ms,
    )
