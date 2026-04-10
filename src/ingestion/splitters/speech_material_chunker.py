import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.ingestion.splitters.document_chunker import DocumentChunker


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PAGE_TAG_PATTERN = re.compile(r"^\[\[PAGE:\d+\]\]$")
STANDALONE_PAGE_NUMBER_PATTERN = re.compile(r"^(?:\d{1,4}|[-—_]\s*\d{1,4}\s*[-—_]|\d{1,4}\s*/\s*\d{1,4})$")


class SpeechMaterialChunker(DocumentChunker):
    """
    讲话精神/重要论述材料分块器。
    适用于“习近平指出/强调/要求”“第一，/第二，”以及论述摘编序号类文本，
    避免把整篇讲话稿按审计报告兜成一个大块。
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        self._heading_patterns: List[Tuple[str, re.Pattern[str]]] = [
            ("chapter", re.compile(r"^[一二三四五六七八九十]+、\s*[^\n]{2,120}$")),
            ("chapter", re.compile(r"^第[一二三四五六七八九十百千万零〇两\d]+[部分章节]\s*[^\n]{0,120}$")),
            ("point", re.compile(r"^(?:第一|第二|第三|第四|第五|第六|第七|第八|第九|第十)[，,、:：]\s*[^\n]{2,}$")),
            ("point", re.compile(r"^[一二三四五六七八九十]是[，,、:：]?\s*[^\n]{2,}$")),
            ("quote", re.compile(r"^(?:习近平(?:总书记)?|他|会议)(?:指出|强调|要求|强调指出|指出强调)[，,、:：]\s*[^\n]{2,}$")),
            ("item", re.compile(r"^\d+[.．、]\s*$")),
            ("item", re.compile(r"^\d+[.．、]\s*[^\n]{2,120}$")),
        ]

    def _is_speech_material(self, document: Dict[str, Any]) -> bool:
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
            if "important_speeches" in label_values:
                return True

        name_sample = f"{filename}\n{title}"
        if any(token in name_sample for token in ["重要讲话", "讲话精神", "重要论述", "论述摘编"]):
            return True

        text_sample = text[:5000]
        speech_marker_count = sum(
            text_sample.count(marker)
            for marker in ["习近平指出", "习近平强调", "习近平要求", "习近平总书记指出", "习近平总书记强调"]
        )
        if speech_marker_count >= 2 and any(token in text_sample for token in ["中央纪委", "全面从严治党", "党风廉政"]):
            return True

        return False

    def chunk_speech_material(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        text = str(document.get("text", "") or "")
        filename = str(document.get("filename", "unknown") or "unknown")
        logger.info("开始按讲话材料结构分块文档: %s", filename)

        sections = self._identify_sections(text.split("\n"))
        chunks = self._build_chunks(document, sections)

        logger.info("讲话材料分块完成，共生成 %s 个文本块", len(chunks))
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

            section_type, header = self._check_section_header(stripped)
            if section_type:
                if current is not None:
                    sections.append(current)
                current = {
                    "type": section_type,
                    "header": header,
                    "content_lines": pending_page_tags + [line],
                }
                pending_page_tags = []
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

    def _check_section_header(self, line: str) -> Tuple[Optional[str], str]:
        candidate = str(line or "").strip()
        if not candidate:
            return None, ""
        if len(candidate) > 180:
            return None, ""
        if re.search(r"[.．…·•]{2,}\s*\d+\s*$", candidate):
            return None, ""

        for section_type, pattern in self._heading_patterns:
            if pattern.match(candidate):
                return section_type, candidate
        return None, ""

    def _build_chunks(self, document: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        target_size = max(480, min(self.chunk_size, 900))

        current_chapter = ""
        buffer_sections: List[Dict[str, Any]] = []
        buffer_text = ""

        def section_text(section: Dict[str, Any]) -> str:
            return self._normalize_chunk_lines(section.get("content_lines") or [])

        def section_to_chunk_text(section: Dict[str, Any]) -> str:
            text = section_text(section)
            section_type = str(section.get("type", "") or "")
            header = str(section.get("header", "") or "").strip()
            if current_chapter and section_type in {"point", "quote", "item"} and header != current_chapter:
                return f"{current_chapter}\n{text}".strip()
            return text

        def flush() -> None:
            nonlocal buffer_sections, buffer_text
            if not buffer_text.strip() or not buffer_sections:
                buffer_sections = []
                buffer_text = ""
                return

            first_section = buffer_sections[0]
            last_section = buffer_sections[-1]
            header = str(first_section.get("header", "") or "").strip()
            section_path = [current_chapter] if current_chapter and header != current_chapter else []
            chunks.append(self._create_chunk(
                document=document,
                text=buffer_text.strip(),
                header=header,
                section_path=section_path,
                semantic_boundary=str(last_section.get("type", "") or "content"),
            ))
            buffer_sections = []
            buffer_text = ""

        for section in sections:
            section_type = str(section.get("type", "") or "")
            header = str(section.get("header", "") or "").strip()

            if section_type == "chapter":
                flush()
                current_chapter = header

            text_for_chunk = section_to_chunk_text(section)
            if not text_for_chunk:
                continue

            if len(text_for_chunk) > target_size:
                flush()
                split_texts = self._split_by_target_length(text_for_chunk, target_size)
                for part in split_texts:
                    clean_part = str(part or "").strip()
                    if not clean_part:
                        continue
                    section_path = [current_chapter] if current_chapter and header != current_chapter else []
                    chunks.append(self._create_chunk(
                        document=document,
                        text=clean_part,
                        header=header,
                        section_path=section_path,
                        semantic_boundary=section_type or "content",
                    ))
                continue

            potential_text = "\n".join([item for item in [buffer_text.strip(), text_for_chunk] if item]).strip()
            should_flush = bool(buffer_text.strip()) and (
                len(potential_text) > target_size or section_type in {"chapter", "quote"}
            )

            if should_flush:
                flush()
                potential_text = text_for_chunk

            buffer_sections.append(section)
            buffer_text = potential_text

        flush()
        return chunks

    @staticmethod
    def _looks_like_display_boundary(line: str) -> bool:
        candidate = str(line or "").strip()
        if not candidate:
            return False
        return bool(
            PAGE_TAG_PATTERN.match(candidate)
            or re.match(r"^[一二三四五六七八九十]+、\s*[^\n]{2,120}$", candidate)
            or re.match(r"^第[一二三四五六七八九十百千万零〇两\d]+[部分章节]\s*[^\n]{0,120}$", candidate)
            or re.match(r"^(?:第一|第二|第三|第四|第五|第六|第七|第八|第九|第十)[，,、:：]\s*[^\n]{2,}$", candidate)
            or re.match(r"^[一二三四五六七八九十]是[，,、:：]?\s*[^\n]{2,}$", candidate)
            or re.match(r"^(?:习近平(?:总书记)?|他|会议)(?:指出|强调|要求|强调指出|指出强调)[，,、:：]\s*[^\n]{2,}$", candidate)
            or re.match(r"^\d+[.．、]\s*$", candidate)
        )

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

            if PAGE_TAG_PATTERN.match(previous) or cls._looks_like_display_boundary(line):
                parts.append(line)
                continue

            if re.search(r"[。！？!?；;：:]$", previous):
                parts.append(line)
                continue

            parts[-1] = f"{previous}{line}"

        return "\n".join(parts).strip()

    @staticmethod
    def _split_by_target_length(text: str, target_size: int) -> List[str]:
        chunks: List[str] = []
        source = str(text or "").strip()
        start = 0
        safe_target = max(240, int(target_size or 512))

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

    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        all_chunks: List[Dict[str, Any]] = []
        for doc in documents:
            if self.__class__ == SpeechMaterialChunker or self._is_speech_material(doc):
                chunks = self.chunk_speech_material(doc)
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
        }
