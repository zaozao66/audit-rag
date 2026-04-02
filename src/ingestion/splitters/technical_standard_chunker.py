import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.ingestion.splitters.document_chunker import DocumentChunker


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PAGE_TAG_PATTERN = re.compile(r"^\[\[PAGE:\d+\]\]$")


class TechnicalStandardChunker(DocumentChunker):
    """
    技术规范/标准类文档分块器。
    适用于“1 范围 / 3.5 业务网 / 附录A / A.1 / A01.01”这类结构，
    避免被法规条文分块器吞成超大块。
    """

    def __init__(self, chunk_size: int = 1024, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        self._toc_entry_pattern = re.compile(r"[.．…·•]{2,}\s*[IVXLC\d]+\s*$")
        self._heading_patterns: List[Tuple[str, re.Pattern[str]]] = [
            ("appendix", re.compile(r"^附\s*录\s*[A-ZＡ-Ｚ][^\n]*$")),
            ("appendix_section", re.compile(r"^[A-Z]\.\d+(?:\.\d+)?\s*[^\n]*$")),
            ("control_item", re.compile(r"^[A-Z]{1,3}\d+(?:\.\d+)+\s*[^\n]*$")),
            ("level3", re.compile(r"^\d+\.\d+\.\d+\s*[^\n]*$")),
            ("level2", re.compile(r"^\d+\.\d+\s*[^\n]*$")),
            ("level1", re.compile(r"^\d+\s+[^\n]*$")),
            ("preamble", re.compile(r"^(前\s*言|引\s*言|目\s*次|目次)\s*$")),
        ]

    def _is_technical_standard(self, document: Dict[str, Any]) -> bool:
        filename = str(document.get("filename", "") or "")
        text = str(document.get("text", "") or "")
        sample = f"{filename}\n{text[:5000]}"

        filename_has_standard = any(token in filename for token in ["规范", "标准", "技术标准", "技术规范"])
        has_standard_code = bool(re.search(r"\bICS\b|Q/[A-Z]+|GB/T|JR/T", sample))
        has_standard_sections = sum(
            1
            for token in ["规范性引用文件", "术语和定义", "附录 A", "附录A", "前言", "引言"]
            if token in sample
        )
        has_appendix_structure = bool(re.search(r"附\s*录\s*[A-ZＡ-Ｚ]", sample))

        if has_standard_code and (has_standard_sections >= 1 or has_appendix_structure):
            return True
        if filename_has_standard and has_standard_sections >= 2:
            return True
        return False

    def chunk_technical_standard(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        text = str(document.get("text", "") or "")
        filename = str(document.get("filename", "unknown") or "unknown")
        logger.info("开始按技术规范结构分块文档: %s", filename)

        sections = self._identify_sections(text.split("\n"))
        chunks: List[Dict[str, Any]] = []

        current_level1 = ""
        current_level2 = ""
        current_appendix = ""
        current_appendix_section = ""

        for section in sections:
            section_type = str(section.get("type", "") or "")
            header = str(section.get("header", "") or "").strip()
            raw_lines = [str(line or "") for line in (section.get("content_lines") or [])]
            body_lines = self._strip_heading_from_body(raw_lines, header)

            if section_type in {"preamble", "level1"}:
                current_level1 = header
                current_level2 = ""
                current_appendix = ""
                current_appendix_section = ""
                section_path: List[str] = []
                semantic_boundary = "chapter"
            elif section_type == "level2":
                current_level2 = header
                current_appendix = ""
                current_appendix_section = ""
                section_path = [item for item in [current_level1] if item]
                semantic_boundary = "section"
            elif section_type == "level3":
                section_path = [item for item in [current_level1, current_level2] if item]
                semantic_boundary = "article"
            elif section_type == "appendix":
                current_appendix = header
                current_appendix_section = ""
                current_level1 = ""
                current_level2 = ""
                section_path = []
                semantic_boundary = "chapter"
            elif section_type == "appendix_section":
                current_appendix_section = header
                section_path = [item for item in [current_appendix] if item]
                semantic_boundary = "section"
            elif section_type == "control_item":
                section_path = [item for item in [current_appendix, current_appendix_section] if item]
                semantic_boundary = "article"
            else:
                section_path = [item for item in [current_level1, current_level2, current_appendix, current_appendix_section] if item]
                semantic_boundary = "content"

            split_chunks = self._build_chunks_for_section(
                document=document,
                header=header,
                section_path=section_path,
                semantic_boundary=semantic_boundary,
                body_lines=body_lines,
            )
            chunks.extend(split_chunks)

        logger.info("技术规范文档分块完成，共生成 %s 个文本块", len(chunks))
        return chunks

    def _identify_sections(self, lines: List[str]) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        pending_page_tags: List[str] = []

        for raw_line in lines:
            line = str(raw_line or "").rstrip()
            stripped = line.strip()

            if not stripped:
                if current is not None:
                    current["content_lines"].append(line)
                continue

            if PAGE_TAG_PATTERN.match(stripped):
                pending_page_tags.append(stripped)
                continue

            section_type, header, inline_body = self._check_section_header(stripped)
            if section_type:
                if current is not None:
                    sections.append(current)
                content_lines = pending_page_tags + [header]
                if inline_body:
                    content_lines.append(inline_body)
                pending_page_tags = []
                current = {
                    "type": section_type,
                    "header": header,
                    "content_lines": content_lines,
                }
                continue

            if current is None:
                current = {
                    "type": "content",
                    "header": "",
                    "content_lines": pending_page_tags + [line],
                }
                pending_page_tags = []
            else:
                if pending_page_tags:
                    current["content_lines"].extend(pending_page_tags)
                    pending_page_tags = []
                current["content_lines"].append(line)

        if current is not None:
            sections.append(current)
        elif pending_page_tags:
            sections.append({
                "type": "content",
                "header": "",
                "content_lines": pending_page_tags,
            })

        return sections

    def _check_section_header(self, line: str) -> Tuple[Optional[str], str, str]:
        candidate = str(line or "").strip()
        if not candidate:
            return None, "", ""
        if len(candidate) > 120:
            return None, "", ""
        if self._toc_entry_pattern.search(candidate):
            return None, "", ""

        for section_type, pattern in self._heading_patterns:
            if pattern.match(candidate):
                header, inline_body = self._split_inline_heading_body(section_type, candidate)
                return section_type, header, inline_body
        return None, "", ""

    def _split_inline_heading_body(self, section_type: str, line: str) -> Tuple[str, str]:
        candidate = str(line or "").strip()

        if section_type == "appendix":
            close_paren = max(candidate.find("）"), candidate.find(")"))
            if 0 < close_paren < len(candidate) - 1:
                header = candidate[: close_paren + 1].strip()
                inline_body = candidate[close_paren + 1 :].strip()
                if inline_body:
                    return header, inline_body
            return candidate, ""

        prefix_match = re.match(r"^((?:\d+(?:\.\d+){0,2})|(?:[A-Z]{1,3}\d+(?:\.\d+)+)|(?:[A-Z]\.\d+(?:\.\d+)?))\s*", candidate)
        if not prefix_match:
            return candidate, ""

        prefix = prefix_match.group(1).strip()
        remainder = candidate[prefix_match.end():].strip()
        if not remainder:
            return candidate, ""

        split_keywords = ["下列", "根据", "是指", "包括", "对于", "用于", "应当", "应", "凡是", "本文件", "本规范", "本标准"]
        split_at = -1
        for keyword in split_keywords:
            idx = remainder.find(keyword)
            if idx == -1:
                continue
            if 2 <= idx <= 24 and (split_at == -1 or idx < split_at):
                split_at = idx

        if split_at == -1:
            return candidate, ""

        title = remainder[:split_at].strip(" \t:：;；,，")
        inline_body = remainder[split_at:].strip()
        if not title or not inline_body:
            return candidate, ""

        return f"{prefix} {title}".strip(), inline_body

    @staticmethod
    def _strip_heading_from_body(lines: List[str], header: str) -> List[str]:
        if not lines:
            return []
        if not header:
            return [str(line or "") for line in lines]

        body_lines = list(lines)
        for idx, line in enumerate(body_lines):
            stripped = str(line or "").strip()
            if not stripped:
                continue
            if PAGE_TAG_PATTERN.match(stripped):
                continue
            if stripped == header:
                return body_lines[:idx] + body_lines[idx + 1:]
            break
        return body_lines

    def _build_chunks_for_section(
        self,
        document: Dict[str, Any],
        header: str,
        section_path: List[str],
        semantic_boundary: str,
        body_lines: List[str],
    ) -> List[Dict[str, Any]]:
        prefix_lines = [item for item in [*section_path, header] if item]
        body_lines = [str(line or "") for line in body_lines]

        if not body_lines:
            text = "\n".join(prefix_lines).strip()
            if not text:
                return []
            return [self._create_chunk(document, text, header, section_path, semantic_boundary)]

        chunks: List[Dict[str, Any]] = []
        prefix_chars = sum(len(item) + 1 for item in prefix_lines)
        max_body_chars = max(240, self.chunk_size - prefix_chars)

        buffer: List[str] = []
        buffer_size = 0

        def flush() -> None:
            nonlocal buffer, buffer_size
            text_parts = prefix_lines + [line for line in buffer if str(line or "").strip()]
            chunk_text = "\n".join(text_parts).strip()
            if chunk_text:
                chunks.append(self._create_chunk(document, chunk_text, header, section_path, semantic_boundary))
            buffer = []
            buffer_size = 0

        for raw_line in body_lines:
            line = str(raw_line or "")
            line_length = len(line)
            if line_length > max_body_chars:
                if buffer:
                    flush()
                for part in self._split_by_fixed_length(line):
                    buffer = [part]
                    buffer_size = len(part)
                    flush()
                continue

            if buffer and buffer_size + line_length + 1 > max_body_chars:
                flush()

            buffer.append(line)
            buffer_size += line_length + 1

        if buffer:
            flush()

        return chunks

    @staticmethod
    def _create_chunk(
        document: Dict[str, Any],
        text: str,
        header: str,
        section_path: List[str],
        semantic_boundary: str,
    ) -> Dict[str, Any]:
        return {
            "doc_id": document.get("doc_id", ""),
            "filename": document.get("filename", "unknown"),
            "file_type": document.get("file_type", ""),
            "doc_type": document.get("doc_type", "internal_regulation"),
            "title": document.get("title", ""),
            "text": text,
            "semantic_boundary": semantic_boundary,
            "section_path": section_path,
            "header": header,
            "char_count": len(text),
        }
