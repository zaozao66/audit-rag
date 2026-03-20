from typing import Any, Dict, Optional

from flask import Request


_SCOPE_HEADERS = ("X-Knowledge-Scope", "X-RAG-Scope", "X-Scope")


def _normalize_scope(raw: Any) -> Optional[str]:
    value = str(raw or "").strip().lower()
    return value or None


def extract_scope_from_request(request: Request, json_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    for header in _SCOPE_HEADERS:
        value = _normalize_scope(request.headers.get(header))
        if value:
            return value

    value = _normalize_scope(request.args.get("scope"))
    if value:
        return value

    if request.form:
        value = _normalize_scope(request.form.get("scope"))
        if value:
            return value

    payload = json_data
    if payload is None and request.is_json:
        payload = request.get_json(silent=True)

    if isinstance(payload, dict):
        value = _normalize_scope(payload.get("scope"))
        if value:
            return value

    return None
