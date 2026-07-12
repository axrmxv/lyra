"""Юнит-тесты chunker (ADR-002): детерминированность, лимиты, атомарность.

count_tokens подменяется словами — юнит-тесты не требуют модели bge-m3;
реальный токенайзер проверяется live-верификацией фазы.
"""

import pytest

import lyra.ingest.chunker as chunker_module
from lyra.ingest.chunker import chunk_document
from lyra.ingest.ir import Block, BlockType, DocumentIR, Section

CONFIG = {"defaults": {"target_tokens": 20, "max_tokens": 30, "overlap_tokens": 5}}


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunker_module, "count_tokens", lambda text: len(text.split()))


def make_ir(sections: list[Section], fmt: str = "markdown") -> DocumentIR:
    return DocumentIR(
        title="Документ",
        source_type="upload",
        root=Section(children=sections),
        meta={"format": fmt},
    )


def words(n: int, prefix: str = "слово") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_deterministic() -> None:
    ir = make_ir(
        [
            Section(
                heading="Раздел",
                level=1,
                blocks=[Block(type=BlockType.PARAGRAPH, text=words(15))],
            )
        ]
    )
    first = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    second = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    assert [c.text for c in first] == [c.text for c in second]
    assert [c.ordinal for c in first] == list(range(len(first)))


def test_heading_prefix_and_metadata() -> None:
    ir = make_ir(
        [
            Section(
                heading="Политика",
                level=1,
                blocks=[Block(type=BlockType.PARAGRAPH, text="Отпуск 28 дней.")],
                children=[
                    Section(
                        heading="Условия",
                        level=2,
                        blocks=[Block(type=BlockType.PARAGRAPH, text="В первый год.")],
                    )
                ],
            )
        ]
    )
    chunks = chunk_document(ir, chunking_config=CONFIG, doc_meta={"url": "http://x"})
    assert chunks[0].text.startswith("Документ > Политика\n\n")
    nested = [c for c in chunks if c.metadata["headings_path"] == ["Политика", "Условия"]]
    assert len(nested) == 1
    assert nested[0].text.startswith("Документ > Политика > Условия\n\n")
    assert nested[0].metadata["url"] == "http://x"
    assert nested[0].metadata["lang"] == "ru"


def test_blocks_accumulate_until_target() -> None:
    blocks = [Block(type=BlockType.PARAGRAPH, text=words(8, f"p{i}w")) for i in range(5)]
    ir = make_ir([Section(heading="Р", level=1, blocks=blocks)])
    chunks = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    # 5 абзацев по 8 слов при target=20 → минимум 2 chunk, каждый ≤ max+prefix
    assert len(chunks) >= 2
    for chunk in chunks:
        body = chunk.text.split("\n\n", 1)[1]
        assert len(body.split()) <= 30 + 5  # max + допуск overlap-хвоста


def test_table_atomic_and_split_with_header() -> None:
    small_table = "| a | b |\n|---|---|\n| 1 | 2 |"
    rows = "\n".join(f"| ячейка{i} данные{i} значение{i} прочее{i} | v{i} |" for i in range(30))
    big_table = "| col1 | col2 |\n|---|---|\n" + rows
    ir = make_ir(
        [
            Section(
                heading="Т",
                level=1,
                blocks=[
                    Block(type=BlockType.TABLE, text=small_table),
                    Block(type=BlockType.TABLE, text=big_table),
                ],
            )
        ]
    )
    chunks = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    tables = [c for c in chunks if c.metadata["block_type"] == "table"]
    assert tables[0].text.count("| a | b |") == 1  # маленькая таблица целиком
    parts = [c for c in tables if "table_part" in c.metadata]
    assert len(parts) >= 2  # большая разрезана
    for part in parts:
        assert "| col1 | col2 |" in part.text  # шапка повторяется в каждой части


def test_code_atomic() -> None:
    code = "\n".join(f"line_{i} = compute_{i}()" for i in range(40))
    ir = make_ir(
        [
            Section(
                heading="К",
                level=1,
                blocks=[Block(type=BlockType.CODE, text=code, meta={"lang": "python"})],
            )
        ]
    )
    chunks = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    code_chunks = [c for c in chunks if c.metadata["block_type"] == "code"]
    assert len(code_chunks) == 1  # код не режется
    assert code_chunks[0].metadata["code_lang"] == "python"


def test_long_paragraph_split_with_overlap() -> None:
    sentences = ". ".join(words(6, f"s{i}w") for i in range(12)) + "."
    ir = make_ir(
        [Section(heading="Д", level=1, blocks=[Block(type=BlockType.PARAGRAPH, text=sentences)])]
    )
    chunks = chunk_document(ir, chunking_config=CONFIG, doc_meta={})
    assert len(chunks) >= 2
    # Overlap: конец первого chunk встречается в начале второго
    first_body = chunks[0].text.split("\n\n", 1)[1]
    second_body = chunks[1].text.split("\n\n", 1)[1]
    tail_word = first_body.split()[-1].rstrip(".")
    assert tail_word in second_body


def test_low_structure_pdf_uses_fallback_params() -> None:
    config = {
        "defaults": {"target_tokens": 100, "max_tokens": 150, "overlap_tokens": 5},
        "per_source_type": {"pdf": {"fallback": {"target_tokens": 10, "max_tokens": 15}}},
    }
    text = ". ".join(words(4, f"s{i}w") for i in range(8)) + "."
    ir = DocumentIR(
        title="Скан",
        source_type="upload",
        root=Section(blocks=[Block(type=BlockType.PARAGRAPH, text=text)]),
        meta={"format": "pdf", "low_structure": True},
    )
    chunks = chunk_document(ir, chunking_config=config, doc_meta={})
    assert len(chunks) >= 2  # с дефолтным target=100 был бы один
