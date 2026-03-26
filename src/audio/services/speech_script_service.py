import re
import uuid
from dataclasses import dataclass
from typing import Optional


_CITATION_PATTERNS = [
    re.compile(r"\[S\d+\]", flags=re.IGNORECASE),
    re.compile(r"\[\d+\]"),
]


@dataclass
class SpeechScript:
    script_id: str
    speech_text: str
    style: str
    fallback_used: bool


class SpeechScriptService:
    def __init__(self, max_chars: int = 1200):
        self.max_chars = max(200, int(max_chars))

    def build_script(self, text: str, style: Optional[str] = None) -> SpeechScript:
        normalized_style = str(style or "brief").strip().lower() or "brief"
        cleaned = self._cleanup_text(text)
        if not cleaned:
            raise ValueError("缺少可播报文本")

        if normalized_style == "full":
            speech_text = cleaned
        elif normalized_style == "report":
            speech_text = self._to_report_style(cleaned)
        else:
            normalized_style = "brief"
            speech_text = self._to_brief_style(cleaned)

        fallback_used = speech_text == cleaned
        return SpeechScript(
            script_id=f"spk_{uuid.uuid4().hex[:12]}",
            speech_text=speech_text,
            style=normalized_style,
            fallback_used=fallback_used,
        )

    def _cleanup_text(self, text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""

        for pattern in _CITATION_PATTERNS:
            value = pattern.sub("", value)

        # Remove markdown fences and inline code marks.
        value = value.replace("```", "\n").replace("`", "")
        # Strip markdown heading/list markers for oral output.
        value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*\d+\.\s+", "", value, flags=re.MULTILINE)

        value = value.replace("\r", "\n")
        value = re.sub(r"\n{2,}", "\n", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
        value = value.strip()
        if len(value) > self.max_chars:
            value = value[: self.max_chars].rstrip("，,;；。.!？?") + "。"
        return value

    def _to_brief_style(self, text: str) -> str:
        sentences = re.split(r"(?<=[。！？!?；;])", text)
        output = []
        total = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            output.append(sentence)
            total += len(sentence)
            if len(output) >= 4 or total >= min(420, self.max_chars):
                break
        return "".join(output) or text

    def _to_report_style(self, text: str) -> str:
        # Convert line breaks into natural pauses for report-like narration.
        parts = [segment.strip() for segment in text.split("\n") if segment.strip()]
        merged = "。".join(part.rstrip("。！？!?；;" ) for part in parts)
        merged = merged.strip("。")
        return f"以下为重点汇报。{merged}。" if merged else text
