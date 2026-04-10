import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.ingestion.splitters.document_chunker import DocumentChunker


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PAGE_TAG_PATTERN = re.compile(r"^\[\[PAGE:\d+\]\]$")
STANDALONE_PAGE_NUMBER_PATTERN = re.compile(r"^(?:\d{1,4}|[-—_]\s*\d{1,4}\s*[-—_]|\d{1,4}\s*/\s*\d{1,4})$")
BRACKET_HEADING_PATTERN = re.compile(r"【([^】]{1,40})】")

STRUCTURAL_BRACKET_TITLES = {
    "基本案情",
    "处理结果",
    "处分处理",
    "处理处分",
    "案件剖析",
    "案例剖析",
    "剖析治本",
    "忏悔反思",
    "忏悔录",
    "警示教育",
    "纪法提示",
    "纪法依据",
    "办案手记",
    "指导意义",
    "案例点评",
    "点评",
    "实务解读",
}

CASE_MARKERS = [
    "基本案情",
    "案件剖析",
    "案例剖析",
    "剖析治本",
    "忏悔反思",
    "办案手记",
    "纪法提示",
    "违纪违法",
    "涉嫌犯罪",
    "受贿罪",
    "贪污罪",
]


class CaseMaterialChunker(DocumentChunker):
    """
    典型案例库分块器。
    适用于“标题 + 违纪标签 + 基本案情/忏悔反思/剖析治本/纪法提示”结构，
    避免把开头的多个【标签】误识别为多个章节。
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        self._toc_entry_pattern = re.compile(r"[.．…·•]{2,}\s*\d+\s*$")
        self._numbered_heading_pattern = re.compile(
            r"^([一二三四五六七八九十]+、\s*[^\n]{2,80})(.*)$"
        )
        self._point_heading_pattern = re.compile(
            r"^(（[一二三四五六七八九十]+）\s*[^\n]{2,100})(.*)$"
        )

    def _is_case_material(self, document: Dict[str, Any]) -> bool:
        filename = str(document.get("filename", "") or "")
        title = str(document.get("title", "") or "")
        text = str(document.get("text", "") or "")
        labels = document.get("knowledge_labels") or {}

        if isinstance(labels, dict):
            label_values = [
                str(value)
                for values in labels.values()
                for value in (values if isinstance(values, list) else [values])
            ]
            if "case_library" in label_values:
                return True

        name_sample = f"{filename}\n{title}"
        if any(token in name_sample for token in ["典型案例", "案例库", "案件"]):
            return True

        text_sample = text[:5000]
        marker_count = sum(1 for marker in CASE_MARKERS if marker in text_sample)
        has_case_title = "案件" in text_sample[:500]
        has_structural_heading = bool(
            re.search(r"(?:^|\n)[一二三四五六七八九十]+、\s*(?:基本案情|忏悔反思|剖析治本|纪法提示|办案手记)", text_sample)
            or any(f"【{title}】" in text_sample for title in STRUCTURAL_BRACKET_TITLES)
        )
        return has_case_title and has_structural_heading and marker_count >= 2

    def chunk_case_material(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        text = str(document.get("text", "") or "")
        filename = str(document.get("filename", "unknown") or "unknown")
        logger.info("开始按典型案例结构分块文档: %s", filename)

        case_title = self._extract_case_title(document, text)
        case_tags = self._extract_case_tags(text)
        sections = self._identify_sections(text.split("\n"), case_title=case_title)
        chunks = self._build_chunks(document, sections, case_title=case_title, case_tags=case_tags)

        logger.info("典型案例分块完成，共生成 %s 个文本块", len(chunks))
        return chunks

    def _identify_sections(self, lines: List[str], case_title: str) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        pending_page_tags: List[str] = []
        current_top_header = ""

        for raw_line in lines:
            for line in self._expand_inline_structural_bracket_headings(str(raw_line or "").rstrip()):
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

                    if section_type == "chapter":
                        current_top_header = header
                        section_path: List[str] = []
                    else:
                        section_path = [current_top_header] if current_top_header else []

                    content_lines = pending_page_tags + [header]
                    if inline_body:
                        content_lines.append(inline_body)
                    pending_page_tags = []
                    current = {
                        "type": section_type,
                        "header": header,
                        "section_path": section_path,
                        "content_lines": content_lines,
                    }
                    continue

                if current is None:
                    current = {
                        "type": "content",
                        "header": case_title if case_title and not sections else "",
                        "section_path": [],
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
                "header": case_title,
                "section_path": [],
                "content_lines": pending_page_tags,
            })

        return sections

    def _expand_inline_structural_bracket_headings(self, line: str) -> List[str]:
        if not line:
            return [line]

        parts: List[str] = []
        cursor = 0
        for match in BRACKET_HEADING_PATTERN.finditer(line):
            title = match.group(1).strip()
            if title not in STRUCTURAL_BRACKET_TITLES:
                continue
            prefix = line[cursor:match.start()].strip()
            if prefix:
                parts.append(prefix)
            parts.append(match.group(0))
            cursor = match.end()

        suffix = line[cursor:].strip()
        if suffix:
            parts.append(suffix)
        return parts or [line]

    def _check_section_header(self, line: str) -> Tuple[Optional[str], str, str]:
        candidate = str(line or "").strip()
        if not candidate:
            return None, "", ""
        if len(candidate) > 180:
            return None, "", ""
        if self._toc_entry_pattern.search(candidate):
            return None, "", ""

        bracket_match = re.fullmatch(r"【([^】]{1,40})】", candidate)
        if bracket_match:
            title = bracket_match.group(1).strip()
            if title in STRUCTURAL_BRACKET_TITLES:
                return "chapter", candidate, ""
            return None, "", ""

        numbered_match = self._numbered_heading_pattern.match(candidate)
        if numbered_match:
            header = numbered_match.group(1).strip()
            body = numbered_match.group(2).strip()
            if self._looks_like_numbered_case_heading(header):
                return "chapter", header, body

        point_match = self._point_heading_pattern.match(candidate)
        if point_match:
            header = point_match.group(1).strip()
            body = point_match.group(2).strip()
            if self._looks_like_point_heading(header):
                return "section", header, body

        return None, "", ""

    @staticmethod
    def _looks_like_numbered_case_heading(header: str) -> bool:
        candidate = str(header or "").strip()
        if len(candidate) > 100:
            return False
        return any(
            token in candidate
            for token in [
                "基本案情",
                "处理结果",
                "处分处理",
                "案件剖析",
                "案例剖析",
                "剖析治本",
                "忏悔反思",
                "办案手记",
                "纪法提示",
                "纪法依据",
                "警示教育",
            ]
        )

    @staticmethod
    def _looks_like_point_heading(header: str) -> bool:
        candidate = str(header or "").strip()
        if len(candidate) > 120:
            return False
        if re.search(r"[。！？!?；;：:]$", candidate):
            return False
        return len(candidate) >= 5

    def _build_chunks(
        self,
        document: Dict[str, Any],
        sections: List[Dict[str, Any]],
        case_title: str,
        case_tags: List[str],
    ) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        target_size = max(700, min(max(self.chunk_size, 512) * 2, 1400))

        for section in sections:
            text = self._normalize_chunk_lines(section.get("content_lines") or [])
            if not text:
                continue

            section_type = str(section.get("type", "") or "content")
            header = str(section.get("header", "") or "").strip()
            section_path = [str(item).strip() for item in (section.get("section_path") or []) if str(item).strip()]

            if section_type == "content" and header and text.startswith(header):
                text = text[len(header):].lstrip("：:，,。；;、-— \t\n")
                text = f"{header}\n{text}".strip()

            if len(text) <= target_size:
                chunks.append(self._create_chunk(
                    document=document,
                    text=text,
                    header=header,
                    section_path=section_path,
                    semantic_boundary=section_type,
                    case_title=case_title,
                    case_tags=case_tags,
                ))
                continue

            for idx, part in enumerate(self._split_by_target_length(text, target_size)):
                clean_part = str(part or "").strip()
                if not clean_part:
                    continue
                if idx > 0 and header and not clean_part.startswith(header):
                    clean_part = f"{header}\n{clean_part}".strip()
                chunks.append(self._create_chunk(
                    document=document,
                    text=clean_part,
                    header=header,
                    section_path=section_path,
                    semantic_boundary=section_type,
                    case_title=case_title,
                    case_tags=case_tags,
                ))

        return chunks

    @classmethod
    def _normalize_chunk_lines(cls, raw_lines: List[Any]) -> str:
        parts: List[str] = []
        for raw_line in raw_lines:
            line = re.sub(r"\s+", " ", str(raw_line or "")).strip()
            if not line:
                continue
            if STANDALONE_PAGE_NUMBER_PATTERN.match(line):
                continue

            if not parts:
                parts.append(line)
                continue

            previous = parts[-1]
            if PAGE_TAG_PATTERN.match(line):
                if PAGE_TAG_PATTERN.match(previous):
                    continue
                parts[-1] = f"{previous} {line}".strip()
                continue

            if (
                PAGE_TAG_PATTERN.match(previous)
                or cls._looks_like_display_boundary(previous)
                or cls._looks_like_display_boundary(line)
            ):
                parts.append(line)
                continue

            if re.search(r"[。！？!?；;：:]$", previous):
                parts.append(line)
                continue

            parts[-1] = f"{previous}{line}"

        return "\n".join(parts).strip()

    @staticmethod
    def _looks_like_display_boundary(line: str) -> bool:
        candidate = str(line or "").strip()
        if not candidate:
            return False
        return bool(
            PAGE_TAG_PATTERN.match(candidate)
            or re.fullmatch(r"【([^】]{1,40})】", candidate)
            or re.match(r"^[一二三四五六七八九十]+、\s*[^\n]{2,100}$", candidate)
            or re.match(r"^（[一二三四五六七八九十]+）\s*[^\n]{2,120}$", candidate)
        )

    @staticmethod
    def _split_by_target_length(text: str, target_size: int) -> List[str]:
        chunks: List[str] = []
        source = str(text or "").strip()
        start = 0
        safe_target = max(480, int(target_size or 1024))

        while start < len(source):
            end = min(start + safe_target, len(source))
            if end >= len(source):
                chunks.append(source[start:].strip())
                break

            split_at = -1
            for punct in ["。", "；", "：", "！", "？", "\n"]:
                pos = source.rfind(punct, start, end)
                if pos > start + safe_target // 2 and pos > split_at:
                    split_at = pos + 1
            if split_at == -1:
                for punct in ["，", "、", " ", "\t"]:
                    pos = source.rfind(punct, start, end)
                    if pos > start + safe_target // 2 and pos > split_at:
                        split_at = pos + 1

            if split_at == -1:
                split_at = end

            chunk = source[start:split_at].strip()
            if chunk:
                chunks.append(chunk)
            start = split_at

        return chunks

    @staticmethod
    def _extract_case_title(document: Dict[str, Any], text: str) -> str:
        title = str(document.get("title", "") or "").strip()
        if title:
            return title

        for raw_line in str(text or "").splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line or PAGE_TAG_PATTERN.match(line):
                continue
            for match in BRACKET_HEADING_PATTERN.finditer(line):
                if match.group(1).strip() in STRUCTURAL_BRACKET_TITLES:
                    line = line[:match.start()].strip()
                    break
            line = re.sub(r"(【[^】]{1,40}】)+$", "", line).strip()
            if line:
                return line[:160]
        return ""

    @staticmethod
    def _extract_case_tags(text: str) -> List[str]:
        sample = str(text or "")[:1500]
        tags: List[str] = []
        for match in BRACKET_HEADING_PATTERN.finditer(sample):
            title = match.group(1).strip()
            if title in STRUCTURAL_BRACKET_TITLES:
                break
            if title and title not in tags:
                tags.append(title)
        return tags

    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        all_chunks: List[Dict[str, Any]] = []
        for doc in documents:
            if self.__class__ == CaseMaterialChunker or self._is_case_material(doc):
                chunks = self.chunk_case_material(doc)
            else:
                chunks = super().chunk_documents([doc])
            all_chunks.extend(chunks)
        return all_chunks

    @staticmethod
    def _create_chunk(
        document: Dict[str, Any],
        text: str,
        header: str,
        section_path: List[str],
        semantic_boundary: str,
        case_title: str,
        case_tags: List[str],
    ) -> Dict[str, Any]:
        return {
            "doc_id": document.get("doc_id", ""),
            "filename": document.get("filename", "unknown"),
            "file_type": document.get("file_type", ""),
            "doc_type": document.get("doc_type", "internal_report"),
            "title": document.get("title", ""),
            "text": text,
            "semantic_boundary": semantic_boundary,
            "section_path": section_path,
            "header": header,
            "char_count": len(text),
            "case_title": case_title,
            "case_tags": case_tags,
        }
