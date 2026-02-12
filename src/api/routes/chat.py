import json
from typing import Any, Dict, List

from flask import Blueprint, Response, current_app, jsonify, request

from src.api.services.rag_service import RAGService


chat_bp = Blueprint('chat', __name__)


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
        formatted.append(entry)
    return formatted


def _stream_chat_completion(service: RAGService, query: str, top_k: int):
    def _progress(stage: str, status: str, message: str, extra: Dict[str, Any] = None):
        payload = {
            "event": "progress",
            "stage": stage,
            "status": status,
            "message": message,
        }
        if extra:
            payload.update(extra)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        # 先返回一条进度，避免前端长时间无任何流式反馈
        yield _progress("intent", "running", "请求已接收，准备初始化")

        rag_processor = service.get_processor(use_rerank=True, use_llm=True)

        yield _progress("intent", "running", "意图识别中")
        params = rag_processor.router.get_routed_params(query, default_top_k=top_k, use_rerank=True, rerank_top_k=10)
        yield _progress(
            "intent",
            "done",
            f"意图识别完成: {params.get('intent', 'unknown')}",
            {
                "intent": params.get("intent", "unknown"),
                "top_k": params.get("top_k", top_k),
                "use_rerank": params.get("use_rerank", False),
            },
        )

        yield _progress("retrieval", "running", "向量库匹配中")
        search_results = rag_processor.search(
            query,
            top_k=params.get("top_k", top_k),
            use_rerank=params.get("use_rerank", True),
            rerank_top_k=params.get("rerank_top_k", 10),
            doc_types=params.get("doc_types"),
        )
        yield _progress("retrieval", "done", f"检索完成，命中 {len(search_results)} 条结果", {"hits": len(search_results)})

        if not rag_processor.llm_provider:
            raise ValueError("LLM功能未启用，请在初始化时传入llm_provider")

        context_pack = rag_processor.build_contexts_and_citations(search_results)
        contexts = context_pack["contexts"]
        citations = context_pack["citations"]

        yield _progress("generation", "running", "LLM回答生成中")
        model_name = "unknown"
        usage = {}

        for event in rag_processor.llm_provider.stream_generate_answer(query, contexts):
            if event.get("type") == "delta":
                chunk_data = {
                    "choices": [{
                        "delta": {
                            "content": event.get("content", "")
                        },
                        "index": 0,
                        "finish_reason": None,
                    }]
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
            elif event.get("type") == "done":
                model_name = event.get("model", "unknown")
                usage = event.get("usage", {})

        yield _progress("generation", "done", "回答生成完成", {"model": model_name, "usage": usage})
        yield f"data: {json.dumps({'event': 'citations', 'citations': citations}, ensure_ascii=False)}\n\n"

        final_chunk = {
            "choices": [{
                "delta": {},
                "index": 0,
                "finish_reason": "stop",
            }]
        }
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        current_app.logger.error("流式响应生成失败: %s", e, exc_info=True)
        yield _progress("generation", "done", "处理失败", {"error": str(e)})
        error_data = {
            "error": {
                "message": str(e),
                "type": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"


@chat_bp.route('/search_with_intent', methods=['POST'])
def search_with_intent():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor(use_rerank=True, use_llm=True)

        data = request.get_json()
        query = data.get('query')
        if not query:
            return jsonify({"error": "缺少query参数"}), 400

        result = rag_processor.search_with_intent(query, use_rerank=True)
        return jsonify({
            "success": True,
            "query": query,
            "intent": result['intent'],
            "intent_reason": result['intent_reason'],
            "suggested_top_k": result['suggested_top_k'],
            "results": _format_search_results(result['search_results']),
        })
    except Exception as e:
        current_app.logger.error("智能搜索失败: %s", e)
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@chat_bp.route('/ask', methods=['POST'])
def ask_with_llm():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor(use_rerank=True, use_llm=True)

        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400

        query = data['query']
        top_k = data.get('top_k', 5)
        result = rag_processor.search_with_llm_answer(query, top_k=top_k)

        return jsonify({
            "success": True,
            "query": query,
            "intent": result.get('intent', 'unknown'),
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
        current_app.logger.error("LLM问答时出错: %s", e)
        return jsonify({"error": f"LLM问答失败: {str(e)}"}), 500
    except Exception as e:
        current_app.logger.error("LLM问答时出错: %s", e)
        return jsonify({"error": f"LLM问答失败: {str(e)}"}), 500


@chat_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    try:
        service: RAGService = current_app.extensions['rag_service']

        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({"error": "缺少messages字段"}), 400

        messages = data['messages']
        if not messages or not isinstance(messages, list):
            return jsonify({"error": "messages必须是非空数组"}), 400

        user_message = None
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                user_message = msg.get('content', '')
                break

        if not user_message:
            return jsonify({"error": "未找到用户消息"}), 400

        stream = data.get('stream', False)
        top_k = data.get('top_k', 5)

        current_app.logger.info(
            "OpenAI兼容接口收到请求: query='%s...', stream=%s, top_k=%s",
            user_message[:50],
            stream,
            top_k,
        )

        if stream:
            return Response(
                _stream_chat_completion(service, user_message, top_k),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                },
            )

        rag_processor = service.get_processor(use_rerank=True, use_llm=True)
        result = rag_processor.search_with_llm_answer(user_message, top_k=top_k)
        response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": result['answer'],
                },
                "finish_reason": "stop",
                "index": 0,
            }],
            "model": result.get('model', 'unknown'),
            "usage": result.get('llm_usage', {}),
            "intent": result.get('intent', 'unknown'),
            "citations": result.get('citations', []),
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
