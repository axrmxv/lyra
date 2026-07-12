"""TXT → DocumentIR: плоский текст, разбиение по пустым строкам на абзацы."""

from lyra.ingest.ir import Block, BlockType, DocumentIR, Section


def parse_txt(text: str, *, title: str) -> DocumentIR:
    root = Section()
    for raw_paragraph in text.split("\n\n"):
        paragraph = raw_paragraph.strip()
        if paragraph:
            root.blocks.append(Block(type=BlockType.PARAGRAPH, text=paragraph))
    return DocumentIR(title=title, source_type="upload", root=root, meta={"format": "txt"})
