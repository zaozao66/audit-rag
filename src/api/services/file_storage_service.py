import io
import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


logger = logging.getLogger(__name__)

FILE_NOT_FOUND_MESSAGE = "文件不存在"
FILE_BLOB_MISSING_MESSAGE = "文件元数据存在但底层文件缺失"


class FileStorageError(Exception):
    pass


class FileRecordNotFoundError(FileStorageError):
    pass


class FileBlobMissingError(FileStorageError):
    pass


@dataclass
class StoredFileRecord:
    domain: str
    file_id: str
    original_filename: str
    file_type: str
    upload_time: str
    storage_key: str
    file_size: int
    storage_type: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "StoredFileRecord":
        allowed_fields = set(cls.__dataclass_fields__.keys())
        normalized = {k: v for k, v in (raw or {}).items() if k in allowed_fields}
        return cls(**normalized)


class FileMetadataStore:
    def __init__(self, storage_path: str):
        self.storage_path = os.path.abspath(storage_path)
        self._records: Dict[str, StoredFileRecord] = {}
        self._lock = RLock()
        self._ensure_parent_dir()
        self._load()

    def _ensure_parent_dir(self) -> None:
        parent = os.path.dirname(self.storage_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.error("加载统一文件元数据失败: %s", e)
            return

        if not isinstance(payload, dict):
            return

        with self._lock:
            for file_id, raw in payload.items():
                try:
                    record = StoredFileRecord.from_dict(raw)
                    if record.file_id:
                        self._records[record.file_id] = record
                    elif file_id:
                        record.file_id = str(file_id)
                        self._records[record.file_id] = record
                except Exception as e:
                    logger.warning("忽略损坏的统一文件元数据: file_id=%s err=%s", file_id, e)

    def _save_locked(self) -> None:
        payload = {file_id: record.to_dict() for file_id, record in self._records.items()}
        temp_path = f"{self.storage_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.storage_path)

    def add_record(self, record: StoredFileRecord) -> None:
        with self._lock:
            self._records[record.file_id] = record
            self._save_locked()

    def get_record(self, file_id: str) -> Optional[StoredFileRecord]:
        with self._lock:
            return self._records.get(str(file_id or "").strip())

    def delete_record(self, file_id: str) -> bool:
        normalized = str(file_id or "").strip()
        if not normalized:
            return False
        with self._lock:
            if normalized not in self._records:
                return False
            del self._records[normalized]
            self._save_locked()
            return True

    def find_latest_by_filename(self, filename: str, domain: Optional[str] = None) -> Optional[StoredFileRecord]:
        target = str(filename or "").strip()
        if not target:
            return None
        lowered_target = target.lower()
        normalized_domain = _normalize_domain(domain)

        with self._lock:
            matched = []
            for record in self._records.values():
                if normalized_domain and _normalize_domain(record.domain) != normalized_domain:
                    continue
                name = str(record.original_filename or "").strip()
                if not name:
                    continue
                if name == target or name.lower() == lowered_target:
                    matched.append(record)

        if not matched:
            return None
        matched.sort(key=lambda item: str(item.upload_time or ""), reverse=True)
        return matched[0]

    def list_records(
        self,
        file_type: Optional[str] = None,
        keyword: Optional[str] = None,
        domain: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[StoredFileRecord], int]:
        normalized_type = str(file_type or "").strip().lower()
        lowered_keyword = str(keyword or "").strip().lower()
        normalized_domain = _normalize_domain(domain)

        with self._lock:
            records = list(self._records.values())

        filtered: List[StoredFileRecord] = []
        for record in records:
            if normalized_type and str(record.file_type or "").strip().lower() != normalized_type:
                continue
            if lowered_keyword and lowered_keyword not in str(record.original_filename or "").strip().lower():
                continue
            if normalized_domain and _normalize_domain(record.domain) != normalized_domain:
                continue
            filtered.append(record)

        filtered.sort(key=lambda item: str(item.upload_time or ""), reverse=True)
        total = len(filtered)

        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(200, int(page_size or 20)))
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        return filtered[start:end], total


class LocalFileBackend:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    def _full_path(self, storage_key: str) -> str:
        normalized = str(storage_key or "").replace("\\", "/").lstrip("/")
        parts = [part for part in normalized.split("/") if part]
        if any(part == ".." for part in parts):
            raise ValueError("非法 storage_key")
        return os.path.join(self.root_dir, *parts)

    def save_from_path(self, source_path: str, storage_key: str) -> None:
        target = self._full_path(storage_key)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source_path, target)

    def save_bytes(self, data: bytes, storage_key: str) -> None:
        target = self._full_path(storage_key)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)

    def read_bytes(self, storage_key: str) -> bytes:
        path = self._full_path(storage_key)
        with open(path, "rb") as f:
            return f.read()

    def exists(self, storage_key: str) -> bool:
        path = self._full_path(storage_key)
        return os.path.isfile(path)

    def delete(self, storage_key: str) -> None:
        path = self._full_path(storage_key)
        if os.path.isfile(path):
            os.remove(path)

    def resolve_local_path(self, storage_key: str) -> Optional[str]:
        path = self._full_path(storage_key)
        return path if os.path.isfile(path) else None


class MinioFileBackend:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        try:
            import urllib3
            from minio import Minio
            from minio.error import S3Error
        except Exception as e:
            raise RuntimeError("MinIO 依赖未安装，请执行: pip install minio") from e

        raw_endpoint = str(endpoint or "").strip()
        if not raw_endpoint:
            raise ValueError("缺少 MinIO endpoint 配置")
        if "://" not in raw_endpoint:
            raw_endpoint = f"https://{raw_endpoint}"
        parsed = urlparse(raw_endpoint)

        host = parsed.netloc or parsed.path
        if not host:
            raise ValueError("MinIO endpoint 配置无效")

        secure = parsed.scheme.lower() != "http"
        self.bucket = str(bucket or "").strip()
        if not self.bucket:
            raise ValueError("缺少 MinIO bucket 配置")

        urllib3.disable_warnings()
        http_client = urllib3.PoolManager(cert_reqs="CERT_NONE")
        self._s3_error = S3Error
        self.client = Minio(
            host,
            access_key=str(access_key or "").strip(),
            secret_key=str(secret_key or "").strip(),
            secure=secure,
            http_client=http_client,
        )

        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def save_from_path(self, source_path: str, storage_key: str) -> None:
        self.client.fput_object(self.bucket, storage_key, source_path)

    def save_bytes(self, data: bytes, storage_key: str) -> None:
        stream = io.BytesIO(data)
        self.client.put_object(self.bucket, storage_key, stream, len(data))

    def read_bytes(self, storage_key: str) -> bytes:
        response = self.client.get_object(self.bucket, storage_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, storage_key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, storage_key)
            return True
        except self._s3_error as e:
            code = str(getattr(e, "code", "") or "")
            if code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise

    def delete(self, storage_key: str) -> None:
        self.client.remove_object(self.bucket, storage_key)

    @staticmethod
    def resolve_local_path(_storage_key: str) -> Optional[str]:
        return None


def _normalize_domain(value: Optional[str]) -> str:
    domain = str(value or "").strip().lower()
    if domain in {"", "*", "all"}:
        return ""
    return domain


def _infer_file_type(filename: str, provided_type: Optional[str] = None) -> str:
    normalized = str(provided_type or "").strip().lower().lstrip(".")
    if normalized:
        return normalized
    _, ext = os.path.splitext(str(filename or ""))
    return ext.lower().lstrip(".")


class UnifiedFileStorageService:
    def __init__(self, config: Dict[str, object], environment: str = "development"):
        cfg = dict(config or {})
        env = str(environment or "development").strip().lower()

        configured_type = str(cfg.get("storageType") or cfg.get("storage_type") or "").strip().lower()
        if configured_type in {"local", "minio"}:
            storage_type = configured_type
        else:
            storage_type = "minio" if env == "production" else "local"

        local_root_dir = str(cfg.get("localRootDir") or cfg.get("local_root_dir") or "./appData").strip()
        if not local_root_dir:
            local_root_dir = "./appData"

        metadata_path = str(cfg.get("metadataPath") or cfg.get("metadata_path") or "").strip()
        if not metadata_path:
            metadata_path = os.path.join(local_root_dir, "file_storage_metadata.json")

        self.storage_type = storage_type
        self.metadata_store = FileMetadataStore(metadata_path)
        self._lock = RLock()

        if storage_type == "local":
            self._backend = LocalFileBackend(local_root_dir)
        else:
            minio_endpoint = cfg.get("minioEndpoint")
            minio_access_key = cfg.get("minioAccessKey")
            minio_secret_key = cfg.get("minioSecretKey")
            minio_bucket = cfg.get("minioBucket")
            self._backend = MinioFileBackend(
                endpoint=str(minio_endpoint or "").strip(),
                access_key=str(minio_access_key or "").strip(),
                secret_key=str(minio_secret_key or "").strip(),
                bucket=str(minio_bucket or "").strip(),
            )

        logger.info("统一文件存储服务初始化完成: storageType=%s metadata=%s", self.storage_type, metadata_path)

    @staticmethod
    def _build_storage_key(file_id: str, file_type: str) -> str:
        now = datetime.now(timezone.utc)
        ext = str(file_type or "").strip().lower().lstrip(".")
        suffix = f".{ext}" if ext else ".bin"
        return f"{now:%Y/%m/%d}/{file_id}{suffix}"

    @staticmethod
    def _safe_filename(filename: str) -> str:
        raw = str(filename or "").strip()
        raw = raw.replace("/", "_").replace("\\", "_").replace("\x00", "")
        return raw or "unnamed_file"

    def _build_record(self, domain: str, original_filename: str, file_size: int, file_type: str, storage_key: str) -> StoredFileRecord:
        return StoredFileRecord(
            domain=_normalize_domain(domain) or "unknown",
            file_id=uuid.uuid4().hex,
            original_filename=self._safe_filename(original_filename),
            file_type=_infer_file_type(original_filename, file_type),
            upload_time=datetime.now(timezone.utc).isoformat(),
            storage_key=storage_key,
            file_size=max(0, int(file_size or 0)),
            storage_type=self.storage_type,
        )

    def store_from_path(
        self,
        source_path: str,
        original_filename: str,
        domain: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> StoredFileRecord:
        source = str(source_path or "").strip()
        if not source or not os.path.isfile(source):
            raise FileNotFoundError(FILE_NOT_FOUND_MESSAGE)

        size = os.path.getsize(source)
        temp_file_type = _infer_file_type(original_filename, file_type)
        file_id = uuid.uuid4().hex
        storage_key = self._build_storage_key(file_id, temp_file_type)
        record = StoredFileRecord(
            domain=_normalize_domain(domain) or "unknown",
            file_id=file_id,
            original_filename=self._safe_filename(original_filename),
            file_type=temp_file_type,
            upload_time=datetime.now(timezone.utc).isoformat(),
            storage_key=storage_key,
            file_size=size,
            storage_type=self.storage_type,
        )

        with self._lock:
            self._backend.save_from_path(source, storage_key)
            self.metadata_store.add_record(record)
        return record

    def store_bytes(
        self,
        payload: bytes,
        original_filename: str,
        domain: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> StoredFileRecord:
        data = payload or b""
        temp_file_type = _infer_file_type(original_filename, file_type)
        file_id = uuid.uuid4().hex
        storage_key = self._build_storage_key(file_id, temp_file_type)
        record = StoredFileRecord(
            domain=_normalize_domain(domain) or "unknown",
            file_id=file_id,
            original_filename=self._safe_filename(original_filename),
            file_type=temp_file_type,
            upload_time=datetime.now(timezone.utc).isoformat(),
            storage_key=storage_key,
            file_size=len(data),
            storage_type=self.storage_type,
        )

        with self._lock:
            self._backend.save_bytes(data, storage_key)
            self.metadata_store.add_record(record)
        return record

    def get_record(self, file_id: str) -> Optional[StoredFileRecord]:
        return self.metadata_store.get_record(file_id)

    def get_latest_record_by_filename(self, filename: str, domain: Optional[str] = None) -> Optional[StoredFileRecord]:
        return self.metadata_store.find_latest_by_filename(filename, domain=domain)

    def list_files(
        self,
        file_type: Optional[str] = None,
        keyword: Optional[str] = None,
        domain: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, object]], int]:
        records, total = self.metadata_store.list_records(
            file_type=file_type,
            keyword=keyword,
            domain=domain,
            page=page,
            page_size=page_size,
        )
        return [record.to_dict() for record in records], total

    def resolve_local_path(self, file_id: str) -> Optional[str]:
        record = self.metadata_store.get_record(file_id)
        if not record:
            return None
        return self._backend.resolve_local_path(record.storage_key)

    def read_file_by_id(self, file_id: str) -> Tuple[StoredFileRecord, bytes]:
        record = self.metadata_store.get_record(file_id)
        if not record:
            raise FileRecordNotFoundError(FILE_NOT_FOUND_MESSAGE)
        return self._read_record(record)

    def read_file_by_filename(self, filename: str, domain: Optional[str] = None) -> Tuple[StoredFileRecord, bytes]:
        record = self.metadata_store.find_latest_by_filename(filename, domain=domain)
        if not record:
            raise FileRecordNotFoundError(FILE_NOT_FOUND_MESSAGE)
        return self._read_record(record)

    def _read_record(self, record: StoredFileRecord) -> Tuple[StoredFileRecord, bytes]:
        if not self._backend.exists(record.storage_key):
            logger.error(
                "统一文件读取失败: 元数据存在但底层文件缺失 file_id=%s key=%s",
                record.file_id,
                record.storage_key,
            )
            raise FileBlobMissingError(FILE_BLOB_MISSING_MESSAGE)

        data = self._backend.read_bytes(record.storage_key)
        return record, data

    def delete_file(self, file_id: str) -> Dict[str, object]:
        record = self.metadata_store.get_record(file_id)
        if not record:
            raise FileRecordNotFoundError(FILE_NOT_FOUND_MESSAGE)

        if not self._backend.exists(record.storage_key):
            logger.error(
                "统一文件删除失败: 元数据存在但底层文件缺失 file_id=%s key=%s",
                record.file_id,
                record.storage_key,
            )
            raise FileBlobMissingError(FILE_BLOB_MISSING_MESSAGE)

        with self._lock:
            self._backend.delete(record.storage_key)
            try:
                removed = self.metadata_store.delete_record(record.file_id)
            except Exception as e:
                logger.error("统一文件删除后保存元数据失败: file_id=%s err=%s", record.file_id, e)
                raise FileStorageError("底层文件已删除，但元数据更新失败") from e

        if not removed:
            raise FileStorageError("底层文件已删除，但元数据删除失败")

        return {
            "success": True,
            "file_id": record.file_id,
            "original_filename": record.original_filename,
        }

    def delete_files(self, file_ids: List[str]) -> Dict[str, object]:
        normalized_ids = []
        seen = set()
        for file_id in file_ids or []:
            normalized = str(file_id or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_ids.append(normalized)

        if not normalized_ids:
            raise ValueError("缺少有效的 file_ids")

        deleted: List[Dict[str, object]] = []
        failed: List[Dict[str, object]] = []
        for file_id in normalized_ids:
            try:
                result = self.delete_file(file_id)
                deleted.append(result)
            except FileRecordNotFoundError:
                failed.append({
                    "file_id": file_id,
                    "error": FILE_NOT_FOUND_MESSAGE,
                })
            except FileBlobMissingError:
                failed.append({
                    "file_id": file_id,
                    "error": FILE_BLOB_MISSING_MESSAGE,
                })
            except FileStorageError as e:
                failed.append({
                    "file_id": file_id,
                    "error": str(e),
                })

        return {
            "success": len(failed) == 0,
            "requested_count": len(normalized_ids),
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted": deleted,
            "failed": failed,
        }
