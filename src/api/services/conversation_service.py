import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ALLOWED_ROLES = {"user", "assistant", "system"}


@dataclass
class ConversationSession:
    session_id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    summary: str = ""
    last_contexts: List[Dict[str, Any]] = field(default_factory=list)
    last_citations: List[Dict[str, Any]] = field(default_factory=list)
    last_search_results: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ConversationService:
    """Thread-safe in-memory conversation state store."""

    def __init__(self, max_messages: int = 24, ttl_minutes: int = 120):
        self.max_messages = max(6, int(max_messages))
        self.ttl_seconds = max(300, int(ttl_minutes) * 60)
        self._lock = threading.RLock()
        self._sessions: Dict[str, ConversationSession] = {}

    def create_session_id(self) -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _normalize_scope(scope: Optional[str]) -> str:
        return str(scope or "").strip().lower() or "default"

    def _scope_session_key(self, scope: Optional[str], session_id: str) -> str:
        return f"{self._normalize_scope(scope)}:{session_id}"

    def get_or_create_session(self, session_id: Optional[str], scope: Optional[str] = None) -> ConversationSession:
        with self._lock:
            self._prune_expired_locked()
            sid = (session_id or "").strip() or self.create_session_id()
            scoped_key = self._scope_session_key(scope, sid)
            session = self._sessions.get(scoped_key)
            if session is None:
                session = ConversationSession(session_id=sid)
                self._sessions[scoped_key] = session
            session.updated_at = time.time()
            return session

    def sync_client_messages(self, session_id: str, messages: List[Dict[str, Any]], scope: Optional[str] = None) -> None:
        """Use client history as source of truth when it provides multi-turn messages."""
        clean = self._normalize_messages(messages)
        if not clean:
            return

        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            # Only sync if client sends richer history than current store.
            if len(clean) > len(session.messages):
                session.messages = clean[-self.max_messages :]
                session.updated_at = time.time()

    def get_recent_messages(self, session_id: str, max_items: int = 8, scope: Optional[str] = None) -> List[Dict[str, str]]:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            limit = max(1, int(max_items))
            return [dict(m) for m in session.messages[-limit:]]

    def append_messages(self, session_id: str, messages: List[Dict[str, Any]], scope: Optional[str] = None) -> None:
        clean = self._normalize_messages(messages)
        if not clean:
            return

        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            session.messages.extend(clean)
            session.messages = session.messages[-self.max_messages :]
            session.updated_at = time.time()

    def set_summary(self, session_id: str, summary: str, scope: Optional[str] = None) -> None:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            session.summary = (summary or "").strip()
            session.updated_at = time.time()

    def get_summary(self, session_id: str, scope: Optional[str] = None) -> str:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            return session.summary

    def set_last_retrieval(
        self,
        session_id: str,
        contexts: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        search_results: Optional[List[Dict[str, Any]]] = None,
        scope: Optional[str] = None,
    ) -> None:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            session.last_contexts = list(contexts or [])
            session.last_citations = list(citations or [])
            session.last_search_results = list(search_results or [])
            session.updated_at = time.time()

    def get_last_retrieval(self, session_id: str, scope: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            return {
                "contexts": list(session.last_contexts),
                "citations": list(session.last_citations),
                "search_results": list(session.last_search_results),
            }

    def should_refresh_summary(self, session_id: str, every_n_turns: int = 4, scope: Optional[str] = None) -> bool:
        with self._lock:
            session = self.get_or_create_session(session_id, scope=scope)
            pair_turns = len([m for m in session.messages if m.get("role") in {"user", "assistant"}])
            return pair_turns > 0 and pair_turns % max(2, every_n_turns) == 0

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        clean: List[Dict[str, str]] = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).strip().lower()
            if role not in ALLOWED_ROLES:
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(p) for p in content)
            content = str(content).strip()
            if not content:
                continue
            clean.append({"role": role, "content": content})
        return clean

    def _prune_expired_locked(self) -> None:
        now = time.time()
        stale_ids = [
            sid for sid, session in self._sessions.items() if (now - session.updated_at) > self.ttl_seconds
        ]
        for sid in stale_ids:
            self._sessions.pop(sid, None)
