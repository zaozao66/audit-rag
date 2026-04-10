#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
DEFAULT_BATCH_MAX_FILES = 100
DEFAULT_BATCH_MAX_SOURCE_BYTES = 120 * 1024 * 1024
DEFAULT_SERVER_ARCHIVE_LIMIT_BYTES = 200 * 1024 * 1024
DEFAULT_SERVER_SINGLE_FILE_LIMIT_BYTES = 30 * 1024 * 1024


@dataclass
class SourceFile:
    group_name: str
    abs_path: str
    arcname: str
    size: int


@dataclass
class ArchiveBatch:
    group_name: str
    batch_index: int
    files: List[SourceFile]
    source_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按目录分批打包并调用 /upload_archive_store 批量导入文档")
    parser.add_argument("--base-url", required=True, help="接口基础地址，例如 http://127.0.0.1:8000")
    parser.add_argument("--scope", required=True, help="知识域，例如 audit 或 discipline")
    parser.add_argument("--input-dir", required=True, help="待导入文件根目录")
    parser.add_argument("--group-mode", choices=["subdir", "flat"], default="subdir", help="subdir=按一级子目录分组，flat=整个目录为一组")
    parser.add_argument("--root-group-name", default="root", help="flat 模式组名，或 subdir 模式下根目录散落文件的组名")
    parser.add_argument("--doc-type", default="internal_regulation", help="文档类型，例如 internal_regulation")
    parser.add_argument("--chunker-type", default="smart", help="分块器类型，例如 smart / regulation / speech_material / case_material / technical_standard")
    parser.add_argument("--classification-key", default="", help="从分组名派生知识分类的字段 key，例如 library")
    parser.add_argument("--label-map-json", default="", help="分组名到知识分类值的 JSON 映射，例如 {\"国家法律法规\":\"national_laws\"}")
    parser.add_argument("--label-map-file", default="", help="分组名到知识分类值的 JSON 文件路径")
    parser.add_argument("--knowledge-labels-json", default="", help="基准知识分类 JSON，例如 {\"library\":[\"national_laws\"]}")
    parser.add_argument("--knowledge-labels-file", default="", help="基准知识分类 JSON 文件路径")
    parser.add_argument("--searchable", choices=["true", "false"], default="true", help="是否参与检索")
    parser.add_argument("--save-after-processing", choices=["true", "false"], default="true", help="是否每批处理后立即保存")
    parser.add_argument("--batch-max-files", type=int, default=DEFAULT_BATCH_MAX_FILES, help="每批最大文件数")
    parser.add_argument("--batch-max-source-bytes", type=int, default=DEFAULT_BATCH_MAX_SOURCE_BYTES, help="每批源文件总大小上限")
    parser.add_argument("--server-archive-limit-bytes", type=int, default=DEFAULT_SERVER_ARCHIVE_LIMIT_BYTES, help="服务端压缩包大小上限")
    parser.add_argument("--server-single-file-limit-bytes", type=int, default=DEFAULT_SERVER_SINGLE_FILE_LIMIT_BYTES, help="服务端单文件大小上限")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="单批请求超时时间")
    parser.add_argument("--pause-seconds", type=float, default=0.0, help="批次之间暂停秒数")
    parser.add_argument("--auth-token", default="", help="可选鉴权 token")
    parser.add_argument("--auth-scheme", default="Bearer", help="鉴权前缀，默认 Bearer")
    parser.add_argument("--auth-header", default="Authorization", help="鉴权 header 名称")
    parser.add_argument("--verify-ssl", choices=["true", "false"], default="true", help="是否校验证书")
    parser.add_argument("--report-file", default="", help="结果报告输出路径，默认自动生成到当前目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成批次计划，不实际上传")
    parser.add_argument("--stop-on-error", action="store_true", help="任一批次失败即停止")
    return parser.parse_args()


def load_json_object(json_text: str, file_path: str, label: str) -> Dict[str, Any]:
    if json_text.strip():
        try:
            value = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} 不是合法 JSON: {exc}") from exc
    elif file_path.strip():
        with open(file_path, "r", encoding="utf-8") as f:
            value = json.load(f)
    else:
        return {}

    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def normalize_labels(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, list):
            items = [str(item or "").strip() for item in value]
        else:
            items = [str(value).strip()]
        cleaned = [item for item in items if item]
        if cleaned:
            normalized[str(key).strip()] = list(dict.fromkeys(cleaned))
    return normalized


def safe_archive_name(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_").replace("\x00", "")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "batch"


def resolve_group_name(input_dir: Path, file_path: Path, group_mode: str, root_group_name: str) -> Tuple[str, str]:
    relative = file_path.relative_to(input_dir)
    parts = relative.parts
    if group_mode == "flat":
        return root_group_name, relative.as_posix()

    if len(parts) <= 1:
        return root_group_name, relative.name

    group_name = parts[0]
    arcname = Path(*parts[1:]).as_posix()
    return group_name, arcname


def collect_source_files(
    input_dir: Path,
    group_mode: str,
    root_group_name: str,
    single_file_limit_bytes: int,
) -> Tuple[List[SourceFile], List[Dict[str, Any]]]:
    source_files: List[SourceFile] = []
    skipped: List[Dict[str, Any]] = []

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue

        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            skipped.append({"path": str(path), "reason": "unsupported_extension"})
            continue

        size = path.stat().st_size
        if size <= 0:
            skipped.append({"path": str(path), "reason": "empty_file"})
            continue

        if size > single_file_limit_bytes:
            skipped.append(
                {
                    "path": str(path),
                    "reason": "single_file_too_large",
                    "size": size,
                    "limit": single_file_limit_bytes,
                }
            )
            continue

        group_name, arcname = resolve_group_name(input_dir, path, group_mode, root_group_name)
        source_files.append(
            SourceFile(
                group_name=group_name,
                abs_path=str(path),
                arcname=arcname,
                size=size,
            )
        )

    return source_files, skipped


def split_batches(
    files: List[SourceFile],
    batch_max_files: int,
    batch_max_source_bytes: int,
) -> List[ArchiveBatch]:
    grouped: Dict[str, List[SourceFile]] = {}
    for item in files:
        grouped.setdefault(item.group_name, []).append(item)

    batches: List[ArchiveBatch] = []
    for group_name in sorted(grouped.keys()):
        current: List[SourceFile] = []
        current_bytes = 0
        batch_index = 1
        for item in grouped[group_name]:
            exceed_files = len(current) >= batch_max_files
            exceed_bytes = current and current_bytes + item.size > batch_max_source_bytes
            if exceed_files or exceed_bytes:
                batches.append(
                    ArchiveBatch(
                        group_name=group_name,
                        batch_index=batch_index,
                        files=list(current),
                        source_bytes=current_bytes,
                    )
                )
                batch_index += 1
                current = []
                current_bytes = 0

            current.append(item)
            current_bytes += item.size

        if current:
            batches.append(
                ArchiveBatch(
                    group_name=group_name,
                    batch_index=batch_index,
                    files=list(current),
                    source_bytes=current_bytes,
                )
            )

    return batches


def build_batch_labels(
    base_labels: Dict[str, List[str]],
    classification_key: str,
    group_name: str,
    label_map: Dict[str, Any],
    root_group_name: str,
) -> Dict[str, List[str]]:
    labels = {key: list(values) for key, values in base_labels.items()}
    key = classification_key.strip()
    if not key:
        return labels

    if group_name == root_group_name and group_name not in label_map:
        return labels

    mapped = label_map.get(group_name, group_name)
    value = str(mapped or "").strip()
    if not value:
        return labels

    values = labels.setdefault(key, [])
    if value not in values:
        values.append(value)
    return labels


def create_batch_archive(batch: ArchiveBatch) -> Tuple[str, int]:
    archive_prefix = safe_archive_name(f"{batch.group_name}_part{batch.batch_index:03d}_")
    temp = tempfile.NamedTemporaryFile(prefix=archive_prefix, suffix=".zip", delete=False)
    temp.close()

    with zipfile.ZipFile(temp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in batch.files:
            zf.write(item.abs_path, arcname=item.arcname)

    archive_size = os.path.getsize(temp.name)
    return temp.name, archive_size


def upload_batch(
    session: requests.Session,
    base_url: str,
    scope: str,
    archive_path: str,
    archive_name: str,
    doc_type: str,
    chunker_type: str,
    searchable: str,
    save_after_processing: str,
    knowledge_labels: Dict[str, List[str]],
    timeout_seconds: int,
    verify_ssl: bool,
    auth_header: str,
    auth_token: str,
    auth_scheme: str,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/upload_archive_store"
    headers = {"X-Knowledge-Scope": scope}
    if auth_token.strip():
        token_value = auth_token.strip()
        if auth_scheme.strip():
            token_value = f"{auth_scheme.strip()} {token_value}"
        headers[auth_header] = token_value

    data = {
        "doc_type": doc_type,
        "chunker_type": chunker_type,
        "searchable": searchable,
        "save_after_processing": save_after_processing,
    }
    if knowledge_labels:
        data["knowledge_labels"] = json.dumps(knowledge_labels, ensure_ascii=False)

    with open(archive_path, "rb") as f:
        response = session.post(
            url,
            headers=headers,
            data=data,
            files={"archive": (archive_name, f, "application/zip")},
            timeout=timeout_seconds,
            verify=verify_ssl,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:4000]}

    return {
        "status_code": response.status_code,
        "ok": response.ok,
        "payload": payload,
    }


def print_batch_plan(batches: List[ArchiveBatch]) -> None:
    print(f"计划生成 {len(batches)} 个批次")
    for batch in batches:
        print(
            f"- {batch.group_name} / part {batch.batch_index:03d}: "
            f"{len(batch.files)} files, {batch.source_bytes} bytes"
        )


def build_report_path(explicit_path: str) -> str:
    if explicit_path.strip():
        return explicit_path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.abspath(f"batch_import_report_{timestamp}.json")


def summarize_chunk_quality(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not reports:
        return {
            "document_count": 0,
            "chunk_count": 0,
            "documents_with_long_chunks": 0,
            "documents_with_embedding_over_limit_chunks": 0,
            "documents_with_oversized_splits": 0,
            "documents_with_suspected_toc": 0,
            "documents_with_duplicate_prefixes": 0,
            "documents_with_filename_mismatch": 0,
            "top_max_chunk_docs": [],
        }

    return {
        "document_count": len(reports),
        "chunk_count": sum(int(item.get("chunk_count", 0) or 0) for item in reports),
        "documents_with_long_chunks": sum(1 for item in reports if int(item.get("long_chunk_count", 0) or 0) > 0),
        "documents_with_embedding_over_limit_chunks": sum(1 for item in reports if int(item.get("embedding_over_limit_count", 0) or 0) > 0),
        "documents_with_oversized_splits": sum(1 for item in reports if int(item.get("oversized_split_source_count", 0) or 0) > 0),
        "documents_with_suspected_toc": sum(1 for item in reports if int(item.get("suspected_toc_count", 0) or 0) > 0),
        "documents_with_duplicate_prefixes": sum(1 for item in reports if int(item.get("duplicate_prefix_count", 0) or 0) > 0),
        "documents_with_filename_mismatch": sum(1 for item in reports if int(item.get("filename_mismatch_count", 0) or 0) > 0),
        "top_max_chunk_docs": [
            {
                "filename": item.get("filename", ""),
                "batch_group_name": item.get("batch_group_name", ""),
                "chunk_count": item.get("chunk_count", 0),
                "max_chunk_chars": item.get("max_chunk_chars", 0),
                "resolved_chunker_types": item.get("resolved_chunker_types", []),
                "chunker_route_reasons": item.get("chunker_route_reasons", []),
            }
            for item in sorted(reports, key=lambda entry: int(entry.get("max_chunk_chars", 0) or 0), reverse=True)[:10]
        ],
    }


def main() -> int:
    args = parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"输入目录不存在: {input_dir}", file=sys.stderr)
        return 2

    try:
        label_map = load_json_object(args.label_map_json, args.label_map_file, "label_map")
        base_labels = normalize_labels(
            load_json_object(args.knowledge_labels_json, args.knowledge_labels_file, "knowledge_labels")
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2

    source_files, skipped_files = collect_source_files(
        input_dir=input_dir,
        group_mode=args.group_mode,
        root_group_name=args.root_group_name,
        single_file_limit_bytes=args.server_single_file_limit_bytes,
    )
    if not source_files:
        print("没有找到可导入文件", file=sys.stderr)
        return 2

    batches = split_batches(
        files=source_files,
        batch_max_files=max(1, args.batch_max_files),
        batch_max_source_bytes=max(1, args.batch_max_source_bytes),
    )

    print(f"扫描完成: {len(source_files)} 个可导入文件, {len(skipped_files)} 个跳过文件")
    if skipped_files:
        print("跳过文件示例:")
        for item in skipped_files[:10]:
            print(f"- {item['path']} | {item['reason']}")

    print_batch_plan(batches)
    if args.dry_run:
        return 0

    session = requests.Session()
    report: Dict[str, Any] = {
        "base_url": args.base_url,
        "scope": args.scope,
        "input_dir": str(input_dir),
        "doc_type": args.doc_type,
        "chunker_type": args.chunker_type,
        "classification_key": args.classification_key,
        "skipped_files": skipped_files,
        "batches": [],
        "started_at": datetime.now().isoformat(),
    }

    failures = 0
    uploaded = 0
    all_chunk_quality: List[Dict[str, Any]] = []

    for batch in batches:
        knowledge_labels = build_batch_labels(
            base_labels=base_labels,
            classification_key=args.classification_key,
            group_name=batch.group_name,
            label_map=label_map,
            root_group_name=args.root_group_name,
        )

        archive_path = ""
        try:
            archive_path, archive_size = create_batch_archive(batch)
            archive_name = safe_archive_name(f"{batch.group_name}_part{batch.batch_index:03d}.zip")

            if archive_size > args.server_archive_limit_bytes:
                raise ValueError(
                    f"批次压缩包过大: {archive_name} ({archive_size} > {args.server_archive_limit_bytes})"
                )

            print(
                f"上传批次: {batch.group_name} / part {batch.batch_index:03d} | "
                f"{len(batch.files)} files | source={batch.source_bytes} | zip={archive_size}"
            )
            result = upload_batch(
                session=session,
                base_url=args.base_url,
                scope=args.scope,
                archive_path=archive_path,
                archive_name=archive_name,
                doc_type=args.doc_type,
                chunker_type=args.chunker_type,
                searchable=args.searchable,
                save_after_processing=args.save_after_processing,
                knowledge_labels=knowledge_labels,
                timeout_seconds=args.timeout_seconds,
                verify_ssl=args.verify_ssl == "true",
                auth_header=args.auth_header,
                auth_token=args.auth_token,
                auth_scheme=args.auth_scheme,
            )
            payload = result["payload"]
            ok = bool(result["ok"]) and not payload.get("error")
            if ok:
                uploaded += 1
                print(
                    "  成功 | "
                    f"processed={payload.get('processed_count', 0)} "
                    f"skipped={payload.get('skipped_count', 0)} "
                    f"updated={payload.get('updated_count', 0)}"
                )
                chunk_quality_summary = payload.get("chunk_quality_summary")
                if isinstance(chunk_quality_summary, dict) and chunk_quality_summary:
                    print(
                        "  切片质量 | "
                        f"docs={chunk_quality_summary.get('document_count', 0)} "
                        f"chunks={chunk_quality_summary.get('chunk_count', 0)} "
                        f"long_docs={chunk_quality_summary.get('documents_with_long_chunks', 0)} "
                        f"split_docs={chunk_quality_summary.get('documents_with_oversized_splits', 0)} "
                        f"toc_docs={chunk_quality_summary.get('documents_with_suspected_toc', 0)}"
                    )
            else:
                failures += 1
                print(f"  失败 | status={result['status_code']} | payload={payload}", file=sys.stderr)

            batch_chunk_quality = payload.get("chunk_quality")
            if isinstance(batch_chunk_quality, list):
                for item in batch_chunk_quality:
                    if not isinstance(item, dict):
                        continue
                    quality_item = dict(item)
                    quality_item["batch_group_name"] = batch.group_name
                    quality_item["batch_index"] = batch.batch_index
                    quality_item["archive_name"] = archive_name
                    all_chunk_quality.append(quality_item)

            report["batches"].append(
                {
                    "group_name": batch.group_name,
                    "batch_index": batch.batch_index,
                    "file_count": len(batch.files),
                    "source_bytes": batch.source_bytes,
                    "archive_size": archive_size,
                    "archive_name": archive_name,
                    "knowledge_labels": knowledge_labels,
                    "status_code": result["status_code"],
                    "ok": ok,
                    "payload": payload,
                    "files": [item.arcname for item in batch.files],
                }
            )

            if not ok and args.stop_on_error:
                break

            if args.pause_seconds > 0:
                time.sleep(args.pause_seconds)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(
                f"  批次异常 | {batch.group_name} / part {batch.batch_index:03d} | {exc}",
                file=sys.stderr,
            )
            report["batches"].append(
                {
                    "group_name": batch.group_name,
                    "batch_index": batch.batch_index,
                    "file_count": len(batch.files),
                    "source_bytes": batch.source_bytes,
                    "ok": False,
                    "error": str(exc),
                    "files": [item.arcname for item in batch.files],
                }
            )
            if args.stop_on_error:
                break
        finally:
            if archive_path and os.path.exists(archive_path):
                os.unlink(archive_path)

    report["finished_at"] = datetime.now().isoformat()
    report["summary"] = {
        "batch_count": len(report["batches"]),
        "success_batches": uploaded,
        "failed_batches": failures,
        "source_file_count": len(source_files),
        "skipped_file_count": len(skipped_files),
    }
    report["chunk_quality"] = all_chunk_quality
    report["chunk_quality_summary"] = summarize_chunk_quality(all_chunk_quality)

    report_path = build_report_path(args.report_file)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"报告已写入: {report_path}")
    print(
        f"完成: success_batches={report['summary']['success_batches']} "
        f"failed_batches={report['summary']['failed_batches']}"
    )
    quality_summary = report["chunk_quality_summary"]
    if quality_summary["document_count"]:
        print(
            "切片质量汇总: "
            f"docs={quality_summary['document_count']} "
            f"chunks={quality_summary['chunk_count']} "
            f"long_docs={quality_summary['documents_with_long_chunks']} "
            f"split_docs={quality_summary['documents_with_oversized_splits']} "
            f"toc_docs={quality_summary['documents_with_suspected_toc']} "
            f"duplicate_docs={quality_summary['documents_with_duplicate_prefixes']} "
            f"filename_mismatch_docs={quality_summary['documents_with_filename_mismatch']}"
        )
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
