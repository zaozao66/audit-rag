from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TTSRequest:
    input_text: str
    model: str
    voice: str
    audio_format: str = "mp3"
    sample_rate: int = 24000
    speed: float = 1.0
    timeout_sec: float = 20.0
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    scope: Optional[str] = None


@dataclass
class TTSResult:
    audio_bytes: bytes
    mime_type: str
    model: str
    voice: str
    audio_format: str
    sample_rate: int
    provider: str
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTTSProvider(ABC):
    provider_name = "base"

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult:
        """Synthesize speech from text."""
        raise NotImplementedError
