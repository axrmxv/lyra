"""LLM-judge для offline-evals (eval-plan §1, A-9).

Judge работает через тот же Protocol LLMClient (ADR-009): local — Ollama,
cloud — OpenAI-совместимый endpoint (только evals/CI, в runtime судья
не используется). Все вердикты — structured-вызовы с Pydantic-схемами.
"""

from pydantic import BaseModel, Field

from lyra.core.clients.llm import LLMClient, LLMFormatError, OllamaClient
from lyra.core.clients.openai_compat import OpenAICompatClient
from lyra.core.config import Settings
from lyra.evals.prompts import load_judge_prompt


class ClaimVerdict(BaseModel):
    claim: str
    supported: bool


class FaithfulnessVerdict(BaseModel):
    claims: list[ClaimVerdict] = Field(default_factory=list)


class RelevanceVerdict(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class ChunkRelevanceVerdict(BaseModel):
    relevant: bool


class CitationSupportVerdict(BaseModel):
    supported: bool


def build_judge_llm(settings: Settings, provider: str | None = None) -> tuple[LLMClient, str]:
    """(клиент, имя judge-модели) по конфигу; provider переопределяет CLI-флагом."""
    mode = provider or settings.judge_provider
    if mode == "cloud":
        return (
            OpenAICompatClient(
                settings.judge_api_base,
                api_key=settings.judge_api_key,
                model=settings.judge_cloud_model,
                timeout_s=settings.judge_timeout_s,
            ),
            settings.judge_cloud_model,
        )
    return (
        OllamaClient(
            settings.ollama_url,
            generation_model=settings.judge_model,
            grading_model=settings.judge_model,
            timeout_s=settings.judge_timeout_s,
            num_ctx=settings.llm_num_ctx,
        ),
        settings.judge_model,
    )


class Judge:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def faithfulness(self, answer: str, context: str) -> FaithfulnessVerdict:
        prompt, _ = load_judge_prompt("judge_faithfulness")
        try:
            verdict, _result = await self._llm.structured(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"<КОНТЕКСТ>\n{context}\n</КОНТЕКСТ>\n\n<ОТВЕТ>\n{answer}\n</ОТВЕТ>"
                        ),
                    },
                ],
                FaithfulnessVerdict,
                node="judge_faithfulness",
            )
        except LLMFormatError:
            # Судья не смог выдать формат — считаем ответ неподтверждённым
            # целиком (консервативно), а не роняем весь run
            return FaithfulnessVerdict(claims=[ClaimVerdict(claim=answer, supported=False)])
        return verdict

    async def answer_relevance(self, question: str, answer: str) -> float:
        prompt, _ = load_judge_prompt("judge_answer_relevance")
        try:
            verdict, _result = await self._llm.structured(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"<ВОПРОС>\n{question}\n</ВОПРОС>\n\n<ОТВЕТ>\n{answer}\n</ОТВЕТ>"
                        ),
                    },
                ],
                RelevanceVerdict,
                node="judge_answer_relevance",
            )
        except LLMFormatError:
            return 0.0
        return verdict.score

    async def chunk_relevant(
        self, question: str, ground_truth: str | None, chunk_text: str
    ) -> bool:
        prompt, _ = load_judge_prompt("judge_context_precision")
        reference = ground_truth or "(эталонный ответ отсутствует)"
        try:
            verdict, _result = await self._llm.structured(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"<ВОПРОС>\n{question}\n</ВОПРОС>\n\n"
                            f"<ЭТАЛОННЫЙ_ОТВЕТ>\n{reference}\n</ЭТАЛОННЫЙ_ОТВЕТ>\n\n"
                            f"<ФРАГМЕНТ>\n{chunk_text}\n</ФРАГМЕНТ>"
                        ),
                    },
                ],
                ChunkRelevanceVerdict,
                node="judge_context_precision",
            )
        except LLMFormatError:
            return False
        return verdict.relevant

    async def citation_supported(self, statement: str, chunk_text: str) -> bool:
        prompt, _ = load_judge_prompt("judge_citation_support")
        try:
            verdict, _result = await self._llm.structured(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"<УТВЕРЖДЕНИЕ>\n{statement}\n</УТВЕРЖДЕНИЕ>\n\n"
                            f"<ФРАГМЕНТ>\n{chunk_text}\n</ФРАГМЕНТ>"
                        ),
                    },
                ],
                CitationSupportVerdict,
                node="judge_citation_support",
            )
        except LLMFormatError:
            return False
        return verdict.supported
