import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from src.api.routes.scope_utils import extract_scope_from_request
from src.api.services.conversation_service import ConversationService
from src.api.services.rag_service import RAGService


chat_bp = Blueprint('chat', __name__)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    return bool(value)


def _format_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted = []
    for res in results:
        doc = res['document']
        entry = {
            "score": res['score'],
            "text": doc['text'],
            "doc_id": doc.get('doc_id', ''),
            "chunk_id": doc.get('chunk_id', ''),
            "filename": doc.get('filename', ''),
            "file_type": doc.get('file_type', ''),
            "doc_type": doc.get('doc_type', ''),
            "title": doc.get('title', ''),
        }
        if 'original_score' in res:
            entry["original_score"] = res['original_score']
        if 'vector_score' in res:
            entry["vector_score"] = res['vector_score']
        if 'graph_score' in res:
            entry["graph_score"] = res['graph_score']
        formatted.append(entry)
    return formatted


def _parse_retrieval_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return overrides

    if 'retrieval_mode' in data:
        overrides['retrieval_mode'] = str(data.get('retrieval_mode', '')).lower()
    if 'use_graph' in data:
        overrides['use_graph'] = _to_bool(data.get('use_graph'))

    if 'graph_top_k' in data:
        try:
            overrides['graph_top_k'] = int(data.get('graph_top_k'))
        except (TypeError, ValueError):
            pass
    if 'graph_hops' in data:
        try:
            overrides['graph_hops'] = int(data.get('graph_hops'))
        except (TypeError, ValueError):
            pass
    if 'hybrid_alpha' in data:
        try:
            overrides['hybrid_alpha'] = float(data.get('hybrid_alpha'))
        except (TypeError, ValueError):
            pass

    if 'knowledge_filters' in data and isinstance(data.get('knowledge_filters'), dict):
        normalized: Dict[str, List[str]] = {}
        for raw_key, raw_value in (data.get('knowledge_filters') or {}).items():
            key = str(raw_key or '').strip()
            if not key:
                continue
            if isinstance(raw_value, list):
                values = [str(item or '').strip() for item in raw_value if str(item or '').strip()]
            else:
                value = str(raw_value or '').strip()
                values = [value] if value else []
            if values:
                normalized[key] = values
        if normalized:
            overrides['knowledge_filters'] = normalized

    return overrides


def _coerce_legacy_type_filter(
    service: RAGService,
    scope: str,
    data: Dict[str, Any],
    retrieval_overrides: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return retrieval_overrides
    if retrieval_overrides.get("knowledge_filters"):
        return retrieval_overrides

    raw_type = data.get("type")
    if raw_type is None:
        return retrieval_overrides

    type_value = str(raw_type or "").strip()
    if not type_value:
        return retrieval_overrides

    normalized_type = type_value.casefold()
    for field in service.get_scope_classification_fields(scope):
        field_key = str(field.get("key", "")).strip()
        if not field_key:
            continue

        for option in field.get("options", []) or []:
            value = str(option.get("value", "")).strip()
            label = str(option.get("label", "")).strip()
            candidates = {
                candidate.casefold()
                for candidate in (value, label)
                if candidate
            }
            if normalized_type not in candidates:
                continue

            merged = dict(retrieval_overrides)
            merged["knowledge_filters"] = {field_key: [value]}
            return merged

    return retrieval_overrides


def _parse_top_k(value: Any, default: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(50, parsed))


def _normalize_chat_messages(messages: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    if not isinstance(messages, list):
        return normalized

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        content = str(content).strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _extract_latest_user_query(messages: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]]]:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") == "user":
            return msg.get("content", ""), messages[:idx]
    return "", messages


def _prepare_chat_turn(
    service: RAGService,
    conversation_service: ConversationService,
    scope: str,
    messages: List[Dict[str, str]],
    session_id: Optional[str],
    top_k: int,
    retrieval_overrides: Dict[str, Any],
) -> Dict[str, Any]:
    rag_processor = service.get_processor(scope=scope, use_rerank=True, use_llm=True)
    if not rag_processor.llm_provider:
        raise ValueError("LLM功能未启用，请在初始化时传入llm_provider")

    session = conversation_service.get_or_create_session(session_id, scope=scope)
    final_session_id = session.session_id

    query, history_messages = _extract_latest_user_query(messages)
    if not query:
        raise ValueError("未找到用户消息")

    if history_messages:
        conversation_service.sync_client_messages(final_session_id, history_messages, scope=scope)

    recent_messages = conversation_service.get_recent_messages(final_session_id, max_items=8, scope=scope)
    summary = conversation_service.get_summary(final_session_id, scope=scope)

    llm_provider = rag_processor.llm_provider
    has_assistant_history = any(msg.get("role") == "assistant" for msg in recent_messages)
    if summary or has_assistant_history:
        standalone_query = llm_provider.rewrite_query(
            query=query,
            recent_messages=recent_messages,
            conversation_summary=summary,
        )
    else:
        standalone_query = query

    last_retrieval = conversation_service.get_last_retrieval(final_session_id, scope=scope)
    if retrieval_overrides:
        route_info = {"decision": "full_retrieval", "reason": "检测到显式检索参数，强制执行检索"}
    else:
        route_info = llm_provider.route_retrieval(
            query=standalone_query,
            recent_messages=recent_messages,
            has_last_contexts=bool(last_retrieval.get("contexts")),
        )
    route_decision = route_info.get("decision", "full_retrieval")

    contexts: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    search_results: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {
        "intent": "conversation_followup",
        "top_k": int(top_k),
        "use_rerank": False,
        "retrieval_mode": "none",
        "graph_top_k": 0,
        "graph_hops": 0,
        "hybrid_alpha": 0.0,
    }

    if route_decision == "reuse_docs" and last_retrieval.get("contexts"):
        contexts = list(last_retrieval.get("contexts", []))
        citations = list(last_retrieval.get("citations", []))
        search_results = list(last_retrieval.get("search_results", []))
        params["intent"] = "conversation_followup_reuse"
        params["retrieval_mode"] = "reuse_docs"
    elif route_decision == "no_retrieval":
        params["intent"] = "conversation_no_retrieval"
        params["retrieval_mode"] = "none"
    else:
        params = rag_processor.router.get_routed_params(
            standalone_query,
            default_top_k=top_k,
            use_rerank=True,
            rerank_top_k=10,
            retrieval_overrides=retrieval_overrides,
        )
        retrieval_mode = params.get("retrieval_mode", "hybrid")
        search_results = rag_processor.search(
            standalone_query,
            top_k=params.get("top_k", top_k),
            use_rerank=params.get("use_rerank", True),
            rerank_top_k=params.get("rerank_top_k", 10),
            doc_types=params.get("doc_types"),
            use_graph=params.get("use_graph", True),
            retrieval_mode=retrieval_mode,
            graph_top_k=params.get("graph_top_k", 12),
            graph_hops=params.get("graph_hops", 2),
            hybrid_alpha=params.get("hybrid_alpha", 0.65),
        )
        context_pack = rag_processor.build_contexts_and_citations(search_results)
        contexts = context_pack["contexts"]
        citations = context_pack["citations"]
        conversation_service.set_last_retrieval(
            final_session_id,
            contexts=contexts,
            citations=citations,
            search_results=search_results,
            scope=scope,
        )

    return {
        "session_id": final_session_id,
        "query": query,
        "standalone_query": standalone_query,
        "recent_messages": recent_messages,
        "summary": summary,
        "route_decision": route_decision,
        "route_reason": route_info.get("reason", ""),
        "params": params,
        "contexts": contexts,
        "citations": citations,
        "search_results": search_results,
        "llm_provider": llm_provider,
    }


def _finalize_chat_turn(
    conversation_service: ConversationService,
    llm_provider: Any,
    scope: str,
    session_id: str,
    query: str,
    answer: str,
    previous_summary: str,
) -> str:
    conversation_service.append_messages(
        session_id,
        [
            {"role": "user", "content": query},
            {"role": "assistant", "content": answer},
        ],
        scope=scope,
    )

    updated_summary = previous_summary
    if conversation_service.should_refresh_summary(session_id, every_n_turns=4, scope=scope):
        messages_for_summary = conversation_service.get_recent_messages(session_id, max_items=12, scope=scope)
        updated_summary = llm_provider.summarize_messages(
            recent_messages=messages_for_summary,
            previous_summary=previous_summary,
        )
        conversation_service.set_summary(session_id, updated_summary, scope=scope)

    return updated_summary


def _sse_data(payload: Dict[str, Any], event_name: Optional[str] = None) -> str:
    lines: List[str] = []
    if event_name:
        lines.append(f"event: {event_name}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _build_completion_identity(model_name: str) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name or "unknown",
    }


def _stream_chat_completion(
    service: RAGService,
    conversation_service: ConversationService,
    logger: Any,
    scope: str,
    messages: List[Dict[str, str]],
    session_id: Optional[str],
    top_k: int,
    retrieval_overrides: Dict[str, Any],
    emit_meta_events: bool = False,
):
    def _progress(stage: str, status: str, message: str, extra: Dict[str, Any] = None):
        if not emit_meta_events:
            return ""
        payload = {
            "event": "progress",
            "stage": stage,
            "status": status,
            "message": message,
        }
        if extra:
            payload.update(extra)
        return _sse_data(payload, event_name="progress")

    try:
        progress = _progress("intent", "running", "请求已接收，准备初始化会话")
        if progress:
            yield progress

        turn = _prepare_chat_turn(
            service=service,
            conversation_service=conversation_service,
            scope=scope,
            messages=messages,
            session_id=session_id,
            top_k=top_k,
            retrieval_overrides=retrieval_overrides,
        )

        query = turn["query"]
        standalone_query = turn["standalone_query"]
        route_decision = turn["route_decision"]
        route_reason = turn["route_reason"]
        params = turn["params"]
        contexts = turn["contexts"]
        citations = turn["citations"]
        llm_provider = turn["llm_provider"]
        final_session_id = turn["session_id"]
        completion_meta = _build_completion_identity(getattr(llm_provider, "model_name", "unknown"))
        chunk_meta = dict(completion_meta)
        chunk_meta["object"] = "chat.completion.chunk"

        progress = _progress(
            "intent",
            "done",
            f"改写完成，路由策略: {route_decision}",
            {
                "intent": params.get("intent", "unknown"),
                "top_k": params.get("top_k", top_k),
                "use_rerank": params.get("use_rerank", False),
                "retrieval_mode": params.get("retrieval_mode", "none"),
                "session_id": final_session_id,
                "route_reason": route_reason,
            },
        )
        if progress:
            yield progress

        if route_decision == "no_retrieval":
            progress = _progress("retrieval", "done", "当前问题无需检索，直接生成回答", {"hits": 0})
        elif route_decision == "reuse_docs":
            progress = _progress("retrieval", "done", f"复用上轮检索结果 {len(contexts)} 条", {"hits": len(contexts)})
        else:
            retrieval_mode = params.get("retrieval_mode", "hybrid")
            retrieval_label = {
                "vector": "向量检索",
                "graph": "图检索",
                "hybrid": "混合检索",
            }.get(retrieval_mode, "混合检索")
            progress = _progress("retrieval", "done", f"{retrieval_label}完成，命中 {len(contexts)} 条", {"hits": len(contexts)})
        if progress:
            yield progress

        progress = _progress("generation", "running", "LLM回答生成中")
        if progress:
            yield progress
        model_name = "unknown"
        usage: Dict[str, Any] = {}
        answer_chunks: List[str] = []

        for event in llm_provider.stream_generate_answer(
            query=query,
            contexts=contexts,
            conversation_messages=turn["recent_messages"],
            conversation_summary=turn["summary"],
            standalone_query=standalone_query,
        ):
            if event.get("type") == "delta":
                text = event.get("content", "")
                answer_chunks.append(text)
                chunk_data = {
                    **chunk_meta,
                    "choices": [{
                        "delta": {
                            "content": text
                        },
                        "index": 0,
                        "finish_reason": None,
                    }]
                }
                yield _sse_data(chunk_data)
            elif event.get("type") == "done":
                model_name = event.get("model", "unknown")
                usage = event.get("usage", {})

        final_answer = "".join(answer_chunks).strip()
        updated_summary = _finalize_chat_turn(
            conversation_service=conversation_service,
            llm_provider=llm_provider,
            scope=scope,
            session_id=final_session_id,
            query=query,
            answer=final_answer,
            previous_summary=turn["summary"],
        )

        progress = _progress(
            "generation",
            "done",
            "回答生成完成",
            {
                "model": model_name,
                "usage": usage,
                "session_id": final_session_id,
                "standalone_query": standalone_query,
            },
        )
        if progress:
            yield progress
        if emit_meta_events:
            yield _sse_data({"event": "citations", "citations": citations}, event_name="citations")
            yield _sse_data(
                {
                    "event": "session",
                    "session_id": final_session_id,
                    "summary": updated_summary,
                    "scope": scope,
                },
                event_name="session",
            )

        final_chunk = {
            **chunk_meta,
            "choices": [{
                "delta": {},
                "index": 0,
                "finish_reason": "stop",
            }]
        }
        yield _sse_data(final_chunk)
        yield "data: [DONE]\n\n"
        logger.info(
            "OpenAI兼容流式响应完成: scope=%s session_id=%s route=%s retrieval_mode=%s answer_chars=%s",
            scope,
            final_session_id,
            route_decision,
            params.get("retrieval_mode", "none"),
            len(final_answer),
        )
    except Exception as e:
        logger.error("流式响应生成失败: %s", e, exc_info=True)
        progress = _progress("generation", "done", "处理失败", {"error": str(e)})
        if progress:
            yield progress
        if emit_meta_events:
            error_data = {
                "error": {
                    "message": str(e),
                    "type": "internal_error",
                }
            }
            yield _sse_data(error_data, event_name="error")


@chat_bp.route('/search_with_intent', methods=['POST'])
def search_with_intent():
    try:
        service: RAGService = current_app.extensions['rag_service']
        data = request.get_json(silent=True) or {}
        scope = extract_scope_from_request(request, json_data=data)
        rag_processor = service.get_processor(scope=scope, use_rerank=True, use_llm=True)
        query = data.get('query')
        if not query:
            return jsonify({"error": "缺少query参数"}), 400

        retrieval_overrides = _parse_retrieval_overrides(data)
        retrieval_overrides = _coerce_legacy_type_filter(service, rag_processor.scope, data, retrieval_overrides)
        if "knowledge_filters" in retrieval_overrides:
            retrieval_overrides["knowledge_filters"] = service.normalize_scope_knowledge_labels(
                rag_processor.scope,
                retrieval_overrides.get("knowledge_filters"),
                require_required_fields=False,
            )
        result = rag_processor.search_with_intent(
            query,
            use_rerank=True,
            retrieval_overrides=retrieval_overrides,
        )
        return jsonify({
            "success": True,
            "scope": rag_processor.scope,
            "query": query,
            "intent": result['intent'],
            "intent_reason": result['intent_reason'],
            "suggested_top_k": result['suggested_top_k'],
            "retrieval_mode": result.get('retrieval_mode', 'hybrid'),
            "results": _format_search_results(result['search_results']),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("智能搜索失败: %s", e)
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@chat_bp.route('/ask', methods=['POST'])
def ask_with_llm():
    try:
        service: RAGService = current_app.extensions['rag_service']
        data = request.get_json(silent=True) or {}
        scope = extract_scope_from_request(request, json_data=data)
        rag_processor = service.get_processor(scope=scope, use_rerank=True, use_llm=True)
        if not data or 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400

        query = data['query']
        top_k = _parse_top_k(data.get('top_k', 5))
        retrieval_overrides = _parse_retrieval_overrides(data)
        retrieval_overrides = _coerce_legacy_type_filter(service, rag_processor.scope, data, retrieval_overrides)
        if "knowledge_filters" in retrieval_overrides:
            retrieval_overrides["knowledge_filters"] = service.normalize_scope_knowledge_labels(
                rag_processor.scope,
                retrieval_overrides.get("knowledge_filters"),
                require_required_fields=False,
            )
        result = rag_processor.search_with_llm_answer(
            query,
            top_k=top_k,
            retrieval_overrides=retrieval_overrides,
        )

        return jsonify({
            "success": True,
            "scope": rag_processor.scope,
            "query": query,
            "intent": result.get('intent', 'unknown'),
            "retrieval_mode": result.get('retrieval_mode', 'hybrid'),
            "answer": result['answer'],
            "search_results": _format_search_results(result['search_results']),
            "citations": result.get('citations', []),
            "llm_usage": result['llm_usage'],
            "model": result['model'],
        })
    except ValueError as e:
        if "LLM功能未启用" in str(e):
            return jsonify({"error": "LLM功能未配置，请在config.json中配置LLM API密钥"}), 503
        if "向量库不存在" in str(e):
            return jsonify({"error": "向量库不存在，请先存储文档"}), 404
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("LLM问答时出错: %s", e)
        return jsonify({"error": f"LLM问答失败: {str(e)}"}), 500


@chat_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    try:
        service: RAGService = current_app.extensions['rag_service']
        conversation_service: ConversationService = current_app.extensions['conversation_service']

        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({"error": "缺少messages字段"}), 400
        scope = extract_scope_from_request(request, json_data=data)
        resolved_scope = service.resolve_scope(scope)

        messages = _normalize_chat_messages(data['messages'])
        if not messages:
            return jsonify({"error": "messages必须是非空数组"}), 400

        user_message, _ = _extract_latest_user_query(messages)
        if not user_message:
            return jsonify({"error": "未找到用户消息"}), 400

        stream = _to_bool(data.get('stream', False))
        stream_meta = _to_bool(data.get('stream_meta', False))
        top_k = _parse_top_k(data.get('top_k', 5))
        session_id = data.get('session_id')
        retrieval_overrides = _parse_retrieval_overrides(data)
        retrieval_overrides = _coerce_legacy_type_filter(service, resolved_scope, data, retrieval_overrides)
        if "knowledge_filters" in retrieval_overrides:
            retrieval_overrides["knowledge_filters"] = service.normalize_scope_knowledge_labels(
                resolved_scope,
                retrieval_overrides.get("knowledge_filters"),
                require_required_fields=False,
            )

        current_app.logger.info(
            "OpenAI兼容接口收到请求: scope=%s query='%s...', stream=%s, top_k=%s, retrieval_mode=%s, session_id=%s",
            resolved_scope,
            user_message[:50],
            stream,
            top_k,
            retrieval_overrides.get("retrieval_mode", "auto"),
            session_id or "new",
        )

        if stream:
            stream_logger = current_app.logger
            return Response(
                stream_with_context(
                    _stream_chat_completion(
                        service=service,
                        conversation_service=conversation_service,
                        logger=stream_logger,
                        scope=resolved_scope,
                        messages=messages,
                        session_id=session_id,
                        top_k=top_k,
                        retrieval_overrides=retrieval_overrides,
                        emit_meta_events=stream_meta,
                    )
                ),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                },
            )

        turn = _prepare_chat_turn(
            service=service,
            conversation_service=conversation_service,
            scope=resolved_scope,
            messages=messages,
            session_id=session_id,
            top_k=top_k,
            retrieval_overrides=retrieval_overrides,
        )

        llm_result = turn["llm_provider"].generate_answer(
            query=turn["query"],
            contexts=turn["contexts"],
            conversation_messages=turn["recent_messages"],
            conversation_summary=turn["summary"],
            standalone_query=turn["standalone_query"],
        )
        completion_meta = _build_completion_identity(llm_result.get('model', 'unknown'))

        updated_summary = _finalize_chat_turn(
            conversation_service=conversation_service,
            llm_provider=turn["llm_provider"],
            scope=resolved_scope,
            session_id=turn["session_id"],
            query=turn["query"],
            answer=llm_result["answer"],
            previous_summary=turn["summary"],
        )

        response = {
            **completion_meta,
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": llm_result['answer'],
                },
                "finish_reason": "stop",
                "index": 0,
            }],
            "model": llm_result.get('model', 'unknown'),
            "usage": llm_result.get('usage', {}),
            "intent": turn["params"].get('intent', 'unknown'),
            "retrieval_mode": turn["params"].get('retrieval_mode', 'none'),
            "route_decision": turn["route_decision"],
            "route_reason": turn["route_reason"],
            "standalone_query": turn["standalone_query"],
            "session_id": turn["session_id"],
            "scope": resolved_scope,
            "summary": updated_summary,
            "search_results": _format_search_results(turn["search_results"]),
            "citations": turn["citations"],
        }
        return jsonify(response)
    except ValueError as e:
        if "LLM功能未启用" in str(e):
            return jsonify({
                "error": {
                    "message": "LLM功能未配置，请在config.json中配置LLM API密钥",
                    "type": "service_unavailable",
                    "code": 503,
                }
            }), 503
        if "向量库不存在" in str(e):
            return jsonify({
                "error": {
                    "message": "向量库不存在，请先存储文档",
                    "type": "not_found",
                    "code": 404,
                }
            }), 404
        current_app.logger.error("问答失败: %s", e)
        return jsonify({
            "error": {
                "message": str(e),
                "type": "invalid_request",
                "code": 400,
            }
        }), 400
    except Exception as e:
        current_app.logger.error("问答失败: %s", e, exc_info=True)
        return jsonify({
            "error": {
                "message": f"内部服务错误: {str(e)}",
                "type": "internal_error",
                "code": 500,
            }
        }), 500
