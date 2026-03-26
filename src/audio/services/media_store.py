import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class MediaItem:
    file_name: str
    file_path: str
    audio_url: str
    size_bytes: int
    cache_hit: bool


class MediaStore:
    def __init__(
        self,
        base_dir: str,
        public_base_path: str = "/v1/audio/files",
        ttl_hours: int = 48,
        max_disk_mb: int = 2048,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.public_base_path = "/" + str(public_base_path or "v1/audio/files").strip("/")
        self.ttl_seconds = max(3600, int(ttl_hours) * 3600)
        self.max_disk_bytes = max(200, int(max_disk_mb)) * 1024 * 1024
        self._lock = threading.RLock()
        self._cleanup_counter = 0
        os.makedirs(self.base_dir, exist_ok=True)

    def build_cache_key(self, text: str, provider: str, model: str, voice: str, audio_format: str, sample_rate: int) -> str:
        raw = "||".join(
            [
                provider.strip().lower(),
                model.strip().lower(),
                voice.strip().lower(),
                audio_format.strip().lower(),
                str(sample_rate),
                text.strip(),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def ensure_audio(self, scope: str, cache_key: str, audio_format: str, audio_bytes: Optional[bytes]) -> MediaItem:
        safe_scope = self._safe_scope(scope)
        ext = self._safe_ext(audio_format)
        file_name = f"{safe_scope}__{cache_key[:32]}.{ext}"
        file_path = os.path.join(self.base_dir, file_name)

        with self._lock:
            if os.path.isfile(file_path):
                size_bytes = os.path.getsize(file_path)
                self._touch(file_path)
                self._cleanup_maybe()
                return MediaItem(
                    file_name=file_name,
                    file_path=file_path,
                    audio_url=f"{self.public_base_path}/{file_name}",
                    size_bytes=size_bytes,
                    cache_hit=True,
                )

            if audio_bytes is None:
                raise FileNotFoundError(f"音频缓存不存在: {file_name}")

            with open(file_path, "wb") as f:
                f.write(audio_bytes)

            size_bytes = len(audio_bytes)
            self._cleanup_maybe()
            return MediaItem(
                file_name=file_name,
                file_path=file_path,
                audio_url=f"{self.public_base_path}/{file_name}",
                size_bytes=size_bytes,
                cache_hit=False,
            )

    def resolve_file_path(self, file_name: str) -> Optional[str]:
        normalized = os.path.basename(str(file_name or "").strip())
        if not normalized:
            return None
        candidate = os.path.abspath(os.path.join(self.base_dir, normalized))
        if os.path.commonpath([candidate, self.base_dir]) != self.base_dir:
            return None
        if not os.path.isfile(candidate):
            return None
        self._touch(candidate)
        return candidate

    def _cleanup_maybe(self) -> None:
        self._cleanup_counter += 1
        if self._cleanup_counter % 10 != 0:
            return
        self.cleanup()

    def cleanup(self) -> None:
        now = time.time()
        files = []
        total_size = 0
        for name in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except FileNotFoundError:
                continue
            files.append((path, stat.st_mtime, stat.st_size))
            total_size += stat.st_size

        expired = [item for item in files if (now - item[1]) > self.ttl_seconds]
        for path, _, size in expired:
            try:
                os.remove(path)
                total_size -= size
            except OSError:
                continue

        if total_size <= self.max_disk_bytes:
            return

        files_sorted = sorted(files, key=lambda item: item[1])
        for path, _, size in files_sorted:
            if total_size <= self.max_disk_bytes:
                break
            if not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                total_size -= size
            except OSError:
                continue

    @staticmethod
    def _safe_scope(scope: str) -> str:
        raw = str(scope or "default").strip().lower() or "default"
        normalized = "".join(ch if ch.isalnum() else "_" for ch in raw)
        return normalized[:40] or "default"

    @staticmethod
    def _safe_ext(audio_format: str) -> str:
        raw = str(audio_format or "mp3").strip().lower() or "mp3"
        return "".join(ch for ch in raw if ch.isalnum()) or "mp3"

    @staticmethod
    def _touch(path: str) -> None:
        try:
            now = time.time()
            os.utime(path, (now, now))
        except OSError:
            return
