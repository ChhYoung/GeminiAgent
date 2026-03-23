"""
rag/document.py — 多格式文档解析器

支持解析 PDF、Word (.docx)、Markdown、纯文本文件，
统一返回文本内容列表（按段落/页面分割）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """文档解析后的基本单元。"""

    text: str
    source: str                        # 文件路径或 URL
    page_or_section: int | str = 0     # 页码或章节标识
    metadata: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.text)


class DocumentParser:
    """
    统一文档解析器。

    使用方式：
        parser = DocumentParser()
        chunks = parser.parse("/path/to/doc.pdf")
        for chunk in chunks:
            print(chunk.text[:100])
    """

    def parse(self, path: str) -> list[DocumentChunk]:
        """解析文件，返回文档片段列表。"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = p.suffix.lower()
        dispatch = {
            ".pdf": self._parse_pdf,
            ".docx": self._parse_docx,
            ".doc": self._parse_docx,
            ".md": self._parse_markdown,
            ".markdown": self._parse_markdown,
            ".txt": self._parse_text,
            ".rst": self._parse_text,
            ".csv": self._parse_text,
        }
        parser_fn = dispatch.get(suffix, self._parse_text)
        chunks = list(parser_fn(str(p)))
        logger.debug("Parsed %d chunks from %s", len(chunks), path)
        return chunks

    def parse_text(self, text: str, source: str = "inline") -> list[DocumentChunk]:
        """直接解析字符串内容。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            DocumentChunk(text=para, source=source, page_or_section=i)
            for i, para in enumerate(paragraphs)
        ]

    # ------------------------------------------------------------------
    # 各格式解析器
    # ------------------------------------------------------------------

    def _parse_pdf(self, path: str) -> Iterator[DocumentChunk]:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError("请安装 pypdf: pip install pypdf")
        reader = PdfReader(path)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                yield DocumentChunk(
                    text=text,
                    source=path,
                    page_or_section=i + 1,
                    metadata={"page": i + 1, "total_pages": len(reader.pages)},
                )

    def _parse_docx(self, path: str) -> Iterator[DocumentChunk]:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")
        doc = Document(path)
        section_idx = 0
        buffer: list[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            # 遇到标题时切割
            if para.style.name.startswith("Heading"):
                if buffer:
                    yield DocumentChunk(
                        text="\n".join(buffer),
                        source=path,
                        page_or_section=section_idx,
                    )
                    buffer = []
                    section_idx += 1
                buffer.append(text)
            else:
                buffer.append(text)

        if buffer:
            yield DocumentChunk(
                text="\n".join(buffer),
                source=path,
                page_or_section=section_idx,
            )

    def _parse_markdown(self, path: str) -> Iterator[DocumentChunk]:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # 按二级以上标题切割
        import re
        sections = re.split(r"\n(?=#{1,3} )", content)
        for i, section in enumerate(sections):
            text = section.strip()
            if text:
                # 提取标题
                first_line = text.split("\n")[0].lstrip("#").strip()
                yield DocumentChunk(
                    text=text,
                    source=path,
                    page_or_section=first_line or i,
                    metadata={"section_title": first_line},
                )

    def _parse_text(self, path: str) -> Iterator[DocumentChunk]:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            yield DocumentChunk(text=para, source=path, page_or_section=i)


class TextSplitter:
    """
    文本分块器（Chunking）。

    将长文本切分为适合嵌入的大小，支持重叠滑动窗口。
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separator: str = "\n",
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator

    def split(self, text: str, source: str = "") -> list[DocumentChunk]:
        """将文本切分为固定大小的 chunk，相邻 chunk 之间有重叠。"""
        words = text.split(self.separator)
        chunks: list[DocumentChunk] = []
        start = 0
        idx = 0

        while start < len(words):
            end = start
            length = 0
            while end < len(words) and length + len(words[end]) < self.chunk_size:
                length += len(words[end]) + 1
                end += 1
            if end == start:
                end = start + 1

            chunk_text = self.separator.join(words[start:end])
            chunks.append(
                DocumentChunk(
                    text=chunk_text,
                    source=source,
                    page_or_section=idx,
                )
            )
            idx += 1
            # 滑动窗口（带重叠）
            overlap_chars = 0
            new_start = end
            for j in range(end - 1, start - 1, -1):
                overlap_chars += len(words[j]) + 1
                if overlap_chars >= self.chunk_overlap:
                    new_start = j
                    break
            start = new_start if new_start < end else end

        return chunks

    def split_chunks(
        self, chunks: list[DocumentChunk]
    ) -> list[DocumentChunk]:
        """对已解析的 DocumentChunk 列表做二次分块。"""
        result: list[DocumentChunk] = []
        for chunk in chunks:
            if len(chunk.text) <= self.chunk_size:
                result.append(chunk)
            else:
                sub_chunks = self.split(chunk.text, source=chunk.source)
                for sc in sub_chunks:
                    sc.metadata.update(chunk.metadata)
                result.extend(sub_chunks)
        return result
