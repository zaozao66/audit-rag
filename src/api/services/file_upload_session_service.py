import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Dict, List, Optional


class UploadSessionError(Exception):
    pass


class UploadSessionNotFoundError(UploadSessionError):
    pass


class UploadSessionExpiredError(UploadSessionError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_filename(filename: str) -> str:
    raw = str(filename or "").strip()
    raw = raw.replace("/", "_").replace("\\", "_").replace("\x00", "")
    return raw or "unnamed_file"


@dataclass
class UploadSessionRecord:
    upload_id: str
    domain: str
    original_filename: str
    content_type: str
    file_size: int
    total_chunks: int
    chunk_size: int
    created_at: str
    updated_at: str
    uploaded_chunks: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "UploadSessionRecord":
        payload = dict(raw or {})
        uploaded_chunks = payload.get("uploaded_chunks")
        if not isinstance(uploaded_chunks, dict):
            uploaded_chunks = {}
        normalized_chunks: Dict[str, int] = {}
        for key, value in uploaded_chunks.items():
            try:
                normalized_chunks[str(int(key))] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        return cls(
            upload_id=str(payload.get("upload_id") or "").strip(),
            domain=str(payload.get("domain") or "unknown").strip() or "unknown",
            original_filename=_safe_filename(str(payload.get("original_filename") or "")),
            content_type=str(payload.get("content_type") or "").strip(),
            file_size=max(0, int(payload.get("file_size") or 0)),
            total_chunks=max(1, int(payload.get("total_chunks") or 1)),
            chunk_size=max(1, int(payload.get("chunk_size") or 1)),
            created_at=str(payload.get("created_at") or _utcnow().isoformat()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _utcnow().isoformat()),
            uploaded_chunks=normalized_chunks,
        )

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def missing_chunks(self) -> List[int]:
        return [idx for idx in range(self.total_chunks) if str(idx) not in self.uploaded_chunks]

    def to_public_dict(self) -> Dict[str, object]:
        missing = self.missing_chunks()
        return {
            "upload_id": self.upload_id,
            "domain": self.domain,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "total_chunks": self.total_chunks,
            "chunk_size": self.chunk_size,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "uploaded_chunk_count": len(self.uploaded_chunks),
            "completed": not missing,
            "missing_chunks": missing,
        }


class FileUploadSessionService:
    def __init__(
        self,
        base_dir: str,
        session_ttl_hours: int = 24,
        max_chunk_size_bytes: int = 8 * 1024 * 1024,
    ):
        self.base_dir = os.path.abspath(base_dir or "./appData/upload_sessions")
        self.session_ttl = timedelta(hours=max(1, int(session_ttl_hours or 24)))
        self.max_chunk_size_bytes = max(1, int(max_chunk_size_bytes or 8 * 1024 * 1024))
        self._lock = RLock()
        os.makedirs(self.base_dir, exist_ok=True)

    def create_session(
        self,
        original_filename: str,
        file_size: int,
        total_chunks: int,
        domain: Optional[str] = None,
        content_type: Optional[str] = None,
        chunk_size: Optional[int] = None,
    ) -> Dict[str, object]:
        safe_filename = _safe_filename(original_filename)
        safe_file_size = max(0, int(file_size or 0))
        safe_total_chunks = max(1, int(total_chunks or 1))
        safe_chunk_size = max(1, int(chunk_size or self.max_chunk_size_bytes))
        if safe_chunk_size > self.max_chunk_size_bytes:
            raise ValueError(f"分片大小不能超过 {self.max_chunk_size_bytes} 字节")
        if safe_file_size > 0 and safe_total_chunks * safe_chunk_size < safe_file_size:
            raise ValueError("分片配置不足以覆盖文件总大小")

        self.cleanup_expired_sessions()

        now = _utcnow().isoformat()
        record = UploadSessionRecord(
            upload_id=uuid.uuid4().hex,
            domain=str(domain or "unknown").strip().lower() or "unknown",
            original_filename=safe_filename,
            content_type=str(content_type or "").strip(),
            file_size=safe_file_size,
            total_chunks=safe_total_chunks,
            chunk_size=safe_chunk_size,
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            os.makedirs(self._chunks_dir(record.upload_id), exist_ok=True)
            self._save_record(record)
        return record.to_public_dict()

    def get_session(self, upload_id: str) -> Dict[str, object]:
        record = self._load_record(upload_id)
        self._ensure_not_expired(record)
        return record.to_public_dict()

    def save_chunk(self, upload_id: str, chunk_index: int, source_path: str) -> Dict[str, object]:
        record = self._load_record(upload_id)
        self._ensure_not_expired(record)

        safe_chunk_index = int(chunk_index)
        if safe_chunk_index < 0 or safe_chunk_index >= record.total_chunks:
            raise ValueError("chunk_index 超出范围")

        source = str(source_path or "").strip()
        if not source or not os.path.isfile(source):
            raise FileNotFoundError("分片文件不存在")

        chunk_size = os.path.getsize(source)
        if chunk_size > self.max_chunk_size_bytes:
            raise ValueError(f"分片大小不能超过 {self.max_chunk_size_bytes} 字节")

        target_path = self._chunk_path(record.upload_id, safe_chunk_index)
        with self._lock:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source, target_path)
            record.uploaded_chunks[str(safe_chunk_index)] = chunk_size
            record.updated_at = _utcnow().isoformat()
            self._save_record(record)
        return record.to_public_dict()

    def complete_session(self, upload_id: str, storage_service) -> Dict[str, object]:
        record = self._load_record(upload_id)
        self._ensure_not_expired(record)

        missing = record.missing_chunks()
        if missing:
            preview = ", ".join(str(item) for item in missing[:10])
            raise ValueError(f"仍有分片未上传: {preview}")

        session_dir = self._session_dir(record.upload_id)
        assembled_path = os.path.join(session_dir, "assembled.upload")
        with open(assembled_path, "wb") as output_file:
            for chunk_index in range(record.total_chunks):
                chunk_path = self._chunk_path(record.upload_id, chunk_index)
                if not os.path.isfile(chunk_path):
                    raise ValueError(f"缺少分片: {chunk_index}")
                with open(chunk_path, "rb") as input_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)

        merged_size = os.path.getsize(assembled_path)
        if record.file_size and merged_size != record.file_size:
            raise ValueError("合并后的文件大小与初始化声明不一致")

        stored_record = storage_service.store_from_path(
            source_path=assembled_path,
            original_filename=record.original_filename,
            domain=record.domain,
        )
        self.abort_session(record.upload_id)
        return stored_record.to_dict()

    def abort_session(self, upload_id: str) -> bool:
        session_dir = self._session_dir(upload_id)
        meta_path = self._meta_path(upload_id)
        if not os.path.isdir(session_dir) and not os.path.isfile(meta_path):
            raise UploadSessionNotFoundError("上传会话不存在")

        with self._lock:
            shutil.rmtree(session_dir, ignore_errors=True)
            try:
                os.remove(meta_path)
            except FileNotFoundError:
                pass
        return True

    def cleanup_expired_sessions(self) -> int:
        removed = 0
        for name in os.listdir(self.base_dir):
            upload_id = str(name or "").strip()
            if not upload_id:
                continue
            meta_path = self._meta_path(upload_id)
            if not os.path.isfile(meta_path):
                continue
            try:
                record = self._load_record(upload_id)
                self._ensure_not_expired(record)
            except UploadSessionExpiredError:
                with self._lock:
                    shutil.rmtree(self._session_dir(upload_id), ignore_errors=True)
                    try:
                        os.remove(meta_path)
                    except FileNotFoundError:
                        pass
                removed += 1
            except UploadSessionNotFoundError:
                continue
        return removed

    def _load_record(self, upload_id: str) -> UploadSessionRecord:
        normalized = str(upload_id or "").strip()
        if not normalized:
            raise UploadSessionNotFoundError("缺少 upload_id")
        meta_path = self._meta_path(normalized)
        if not os.path.isfile(meta_path):
            raise UploadSessionNotFoundError("上传会话不存在")
        try:
            with open(meta_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception as exc:
            raise UploadSessionError("读取上传会话失败") from exc
        record = UploadSessionRecord.from_dict(payload)
        if not record.upload_id:
            raise UploadSessionNotFoundError("上传会话不存在")
        return record

    def _save_record(self, record: UploadSessionRecord) -> None:
        meta_path = self._meta_path(record.upload_id)
        temp_path = f"{meta_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(record.to_dict(), file, ensure_ascii=False, indent=2)
        os.replace(temp_path, meta_path)

    def _ensure_not_expired(self, record: UploadSessionRecord) -> None:
        updated_at = datetime.fromisoformat(record.updated_at)
        if (_utcnow() - updated_at) > self.session_ttl:
            raise UploadSessionExpiredError("上传会话已过期，请重新发起上传")

    def _session_dir(self, upload_id: str) -> str:
        normalized = str(upload_id or "").strip()
        if not normalized:
            raise UploadSessionNotFoundError("缺少 upload_id")
        return os.path.join(self.base_dir, normalized)

    def _chunks_dir(self, upload_id: str) -> str:
        return os.path.join(self._session_dir(upload_id), "chunks")

    def _chunk_path(self, upload_id: str, chunk_index: int) -> str:
        return os.path.join(self._chunks_dir(upload_id), f"{int(chunk_index):08d}.part")

    def _meta_path(self, upload_id: str) -> str:
        normalized = str(upload_id or "").strip()
        if not normalized:
            raise UploadSessionNotFoundError("缺少 upload_id")
        return os.path.join(self.base_dir, f"{normalized}.json")


def build_default_upload_temp_dir(base_dir: Optional[str] = None) -> str:
    root = str(base_dir or "").strip()
    if root:
        return os.path.join(os.path.abspath(root), "upload_sessions")
    return os.path.join(tempfile.gettempdir(), "audit-rag-upload-sessions")
