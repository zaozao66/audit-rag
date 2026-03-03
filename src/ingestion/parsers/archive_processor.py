import os
import posixpath
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Set


class ArchiveValidationError(ValueError):
    """Raised when uploaded archive does not satisfy validation rules."""


@dataclass
class ArchiveExtractionResult:
    extracted_paths: List[str]
    original_filenames: List[str]
    unsupported_files: List[str]
    extracted_count: int


def extract_zip_archive(
    archive_path: str,
    output_dir: str,
    allowed_extensions: Optional[Set[str]] = None,
    max_file_count: int = 500,
    max_single_file_bytes: int = 30 * 1024 * 1024,
    max_total_uncompressed_bytes: int = 512 * 1024 * 1024,
    max_compression_ratio: float = 200.0,
) -> ArchiveExtractionResult:
    if allowed_extensions is None:
        allowed_extensions = {'.pdf', '.docx', '.txt'}

    if not zipfile.is_zipfile(archive_path):
        raise ArchiveValidationError("上传文件不是有效的 ZIP 压缩包")

    extracted_paths: List[str] = []
    original_filenames: List[str] = []
    unsupported_files: List[str] = []
    candidates = []
    total_uncompressed_bytes = 0
    output_root = os.path.abspath(output_dir)

    with zipfile.ZipFile(archive_path, 'r') as zf:
        infos = zf.infolist()
        if not infos:
            raise ArchiveValidationError("压缩包为空")

        for info in infos:
            raw_name = str(info.filename or "").replace("\\", "/")
            if not raw_name or raw_name.endswith('/'):
                continue

            if info.flag_bits & 0x1:
                raise ArchiveValidationError(f"压缩包包含加密文件，无法处理: {raw_name}")

            normalized = posixpath.normpath(raw_name).lstrip('/')
            if not normalized or normalized == '.':
                continue
            if normalized.startswith('../') or '/../' in f"/{normalized}":
                raise ArchiveValidationError(f"压缩包路径非法: {raw_name}")

            ext = os.path.splitext(normalized)[1].lower()
            if ext not in allowed_extensions:
                unsupported_files.append(normalized)
                continue

            file_size = int(info.file_size or 0)
            compress_size = int(info.compress_size or 0)
            if file_size <= 0:
                unsupported_files.append(normalized)
                continue

            if file_size > max_single_file_bytes:
                raise ArchiveValidationError(
                    f"文件过大: {normalized} ({file_size} bytes)，超过单文件限制 {max_single_file_bytes} bytes"
                )

            if compress_size > 0:
                ratio = float(file_size) / float(compress_size)
                if ratio > max_compression_ratio:
                    raise ArchiveValidationError(
                        f"文件压缩比异常: {normalized} (ratio={ratio:.1f})，疑似压缩炸弹"
                    )

            total_uncompressed_bytes += file_size
            if total_uncompressed_bytes > max_total_uncompressed_bytes:
                raise ArchiveValidationError(
                    "压缩包解压后总大小超过限制"
                    f" ({total_uncompressed_bytes} > {max_total_uncompressed_bytes} bytes)"
                )

            candidates.append((info, normalized))

        if len(candidates) > max_file_count:
            raise ArchiveValidationError(
                f"压缩包内可处理文件数过多: {len(candidates)}，超过限制 {max_file_count}"
            )

        if not candidates:
            raise ArchiveValidationError("压缩包中没有可处理文件（仅支持 PDF/DOCX/TXT）")

        for info, relative_name in candidates:
            target_path = os.path.abspath(os.path.join(output_root, relative_name))
            if target_path != output_root and not target_path.startswith(output_root + os.sep):
                raise ArchiveValidationError(f"压缩包路径越界: {relative_name}")

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            written = 0
            with zf.open(info, 'r') as src, open(target_path, 'wb') as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_single_file_bytes:
                        raise ArchiveValidationError(
                            f"文件解压后超过单文件限制: {relative_name}"
                        )
                    dst.write(chunk)

            extracted_paths.append(target_path)
            original_filenames.append(relative_name)

    return ArchiveExtractionResult(
        extracted_paths=extracted_paths,
        original_filenames=original_filenames,
        unsupported_files=unsupported_files,
        extracted_count=len(extracted_paths),
    )

