"""Text chunking service.

职责：把已解析出的纯文本切分成适合向量化的结构化片段。
边界：本模块不读取文件、不生成 embedding，也不写入索引。
风险：切分优先寻找自然边界，找不到时才按长度硬切。
"""

import re
from typing import NotRequired, TypedDict, cast


class ChunkPayload(TypedDict):
    """知识库入库链路传递的结构化切片。"""

    content: str
    embedding_content: NotRequired[str]
    meta_info: NotRequired[dict[str, object]]
    section_path: NotRequired[str]
    page_label: NotRequired[str]
    source_path: NotRequired[str]
    chunk_index: NotRequired[int]


MARKDOWN_SUFFIXES = {".md", ".markdown"}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class ChunkingService:
    """按 Markdown 结构、段落边界和固定窗口兜底切分文本。"""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        self.chunk_size = max(200, chunk_size)
        self.chunk_overlap = max(0, min(chunk_overlap, self.chunk_size // 2))

    def split_text(self, text: str, file_suffix: str = ".txt") -> list[ChunkPayload]:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return []

        suffix = file_suffix.lower()
        if suffix in MARKDOWN_SUFFIXES:
            chunks = self._split_markdown(normalized)
        else:
            chunks = self._split_paragraphs(normalized)
        return self._assign_indexes(chunks)

    def _split_markdown(self, text: str) -> list[ChunkPayload]:
        chunks: list[ChunkPayload] = []
        heading_stack: list[str] = []
        section_lines: list[str] = []
        section_path = ""
        in_fence = False

        def flush_section() -> None:
            section_text = "\n".join(section_lines).strip()
            if not section_text:
                return
            chunks.extend(
                self._split_paragraphs(section_text, section_path=section_path)
            )

        for line in text.splitlines():
            if FENCE_RE.match(line):
                in_fence = not in_fence

            heading_match = HEADING_RE.match(line) if not in_fence else None
            if heading_match:
                flush_section()
                section_lines = []

                level = len(heading_match.group(1))
                title = heading_match.group(2).strip().strip("#").strip()
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(title)
                section_path = " / ".join(heading_stack)

            section_lines.append(line)

        flush_section()
        return chunks

    def _split_paragraphs(
        self,
        text: str,
        *,
        section_path: str = "",
    ) -> list[ChunkPayload]:
        blocks = self._paragraph_blocks(text)
        chunks: list[ChunkPayload] = []
        current_blocks: list[str] = []

        def flush_current() -> None:
            content = "\n\n".join(current_blocks).strip()
            current_blocks.clear()
            if content:
                chunks.append(self._make_payload(content, section_path=section_path))

        for block in blocks:
            if len(block) > self.chunk_size:
                flush_current()
                for piece in self._split_fixed_window(block):
                    chunks.append(self._make_payload(piece, section_path=section_path))
                continue

            candidate = "\n\n".join([*current_blocks, block]).strip()
            if current_blocks and len(candidate) > self.chunk_size:
                flush_current()
            current_blocks.append(block)

        flush_current()
        return chunks

    @staticmethod
    def _paragraph_blocks(text: str) -> list[str]:
        blocks: list[str] = []
        current: list[str] = []
        in_fence = False

        for line in text.splitlines():
            if FENCE_RE.match(line):
                in_fence = not in_fence

            if not in_fence and not line.strip():
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
                continue

            current.append(line)

        if current:
            blocks.append("\n".join(current).strip())
        return [block for block in blocks if block]

    def _split_fixed_window(self, text: str) -> list[str]:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(normalized)

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            if end < text_len:
                candidates = [
                    normalized.rfind("\n\n", start, end),
                    normalized.rfind("\n", start, end),
                    normalized.rfind("。", start, end),
                    normalized.rfind(".", start, end),
                    normalized.rfind(" ", start, end),
                ]
                boundary = max(candidates)
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1

            piece = normalized[start:end].strip()
            if piece:
                chunks.append(piece)

            if end >= text_len:
                break
            next_start = max(0, end - self.chunk_overlap)
            if next_start <= start:
                next_start = end
            start = next_start

        return chunks

    @staticmethod
    def _make_payload(content: str, *, section_path: str = "") -> ChunkPayload:
        payload: ChunkPayload = {"content": content}
        if section_path:
            payload["section_path"] = section_path
        return payload

    @staticmethod
    def _assign_indexes(chunks: list[ChunkPayload]) -> list[ChunkPayload]:
        indexed: list[ChunkPayload] = []
        for index, chunk in enumerate(chunks):
            indexed_chunk = dict(chunk)
            indexed_chunk["chunk_index"] = index
            indexed.append(cast(ChunkPayload, indexed_chunk))
        return indexed
