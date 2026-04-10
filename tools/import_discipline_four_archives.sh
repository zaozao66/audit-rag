#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
IMPORT_SCRIPT="${SCRIPT_DIR}/batch_import_archives.py"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SCOPE="${SCOPE:-discipline}"
INPUT_ROOT="${INPUT_ROOT:-${HOME}/clawspace/discipline_import}"
GROUP_MODE="${GROUP_MODE:-flat}"

BATCH_MAX_FILES="${BATCH_MAX_FILES:-100}"
BATCH_MAX_SOURCE_BYTES="${BATCH_MAX_SOURCE_BYTES:-125829120}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-1800}"
VERIFY_SSL="${VERIFY_SSL:-true}"

COMMON_ARGS=(
  --base-url "${BASE_URL}"
  --scope "${SCOPE}"
  --group-mode "${GROUP_MODE}"
  --batch-max-files "${BATCH_MAX_FILES}"
  --batch-max-source-bytes "${BATCH_MAX_SOURCE_BYTES}"
  --timeout-seconds "${TIMEOUT_SECONDS}"
  --verify-ssl "${VERIFY_SSL}"
)

if [[ -n "${AUTH_TOKEN:-}" ]]; then
  COMMON_ARGS+=(--auth-token "${AUTH_TOKEN}")
fi

if [[ -n "${AUTH_SCHEME:-}" ]]; then
  COMMON_ARGS+=(--auth-scheme "${AUTH_SCHEME}")
fi

if [[ -n "${AUTH_HEADER:-}" ]]; then
  COMMON_ARGS+=(--auth-header "${AUTH_HEADER}")
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  COMMON_ARGS+=(--dry-run)
fi

echo "1/4 导入 重要讲话精神"
"${PYTHON_BIN}" "${IMPORT_SCRIPT}" \
  "${COMMON_ARGS[@]}" \
  --input-dir "${INPUT_ROOT}/重要讲话精神" \
  --root-group-name "重要讲话精神" \
  --classification-key library \
  --label-map-json '{"重要讲话精神":"important_speeches"}' \
  --doc-type internal_report \
  --chunker-type speech_material

echo "2/4 导入 国家法律法规"
"${PYTHON_BIN}" "${IMPORT_SCRIPT}" \
  "${COMMON_ARGS[@]}" \
  --input-dir "${INPUT_ROOT}/国家法律法规" \
  --root-group-name "国家法律法规" \
  --classification-key library \
  --label-map-json '{"国家法律法规":"national_laws"}' \
  --doc-type internal_regulation \
  --chunker-type regulation

echo "3/4 导入 常用党内法规"
"${PYTHON_BIN}" "${IMPORT_SCRIPT}" \
  "${COMMON_ARGS[@]}" \
  --input-dir "${INPUT_ROOT}/常用党内法规" \
  --root-group-name "常用党内法规" \
  --classification-key library \
  --label-map-json '{"常用党内法规":"party_regulations"}' \
  --doc-type internal_regulation \
  --chunker-type regulation

echo "4/4 导入 典型案例库"
"${PYTHON_BIN}" "${IMPORT_SCRIPT}" \
  "${COMMON_ARGS[@]}" \
  --input-dir "${INPUT_ROOT}/典型案例库" \
  --root-group-name "典型案例库" \
  --classification-key library \
  --label-map-json '{"典型案例库":"case_library"}' \
  --doc-type internal_report \
  --chunker-type case_material

echo "全部批次执行完成"
