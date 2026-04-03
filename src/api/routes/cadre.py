"""
干部监督智能助手路由

提供以下接口：
  POST /v1/cadre/chat/completions  — 流式对话（SSE，与 chat.py 格式一致）
  GET  /v1/cadre/pdf/<serial>      — 下载/预览任免审批表 PDF
"""

import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from src.llm.providers.llm_provider import create_llm_provider
from src.utils.config_loader import load_config

logger = logging.getLogger(__name__)

cadre_bp = Blueprint("cadre", __name__)

# ---------------------------------------------------------------------------
# 名册数据加载（进程内缓存）
# ---------------------------------------------------------------------------

_roster_lock = threading.Lock()
_roster_cache: Optional[List[Dict[str, Any]]] = None

_ROSTER_PATH = Path(__file__).resolve().parents[3] / "data" / "cadre" / "roster.json"


def _load_roster() -> List[Dict[str, Any]]:
    global _roster_cache
    if _roster_cache is not None:
        return _roster_cache
    with _roster_lock:
        if _roster_cache is not None:
            return _roster_cache
        if not _ROSTER_PATH.exists():
            logger.warning("名册文件不存在: %s", _ROSTER_PATH)
            _roster_cache = []
        else:
            with open(_ROSTER_PATH, encoding="utf-8") as f:
                _roster_cache = json.load(f)
            logger.info("已加载干部名册，共 %d 条记录", len(_roster_cache))
    return _roster_cache


def _roster_as_text() -> str:
    roster = _load_roster()
    return json.dumps(roster, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# LLM Provider（按需初始化，复用同一个实例）
# ---------------------------------------------------------------------------

_llm_lock = threading.Lock()
_llm_provider = None


def _get_llm_provider():
    global _llm_provider
    if _llm_provider is not None:
        return _llm_provider
    with _llm_lock:
        if _llm_provider is not None:
            return _llm_provider
        config = load_config()
        llm_cfg = config.get("llm", {})
        _llm_provider = create_llm_provider(llm_cfg)
    return _llm_provider


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """# 角色设定
你是一名专业的干部关系审查智能助手。
你的职责是帮助用户解答有关干部关系审查领域的各类业务问题。
你了解干部审查领域的业务规则、术语和判断标准，具备专业的业务逻辑能力。

# 你的目标
尽可能准确、高效地回答用户提出的业务问题。
不编造数据库或系统中不存在的事实。
只根据下方提供的【干部名册数据】作答，不得捏造数据中不存在的信息。

# 回答规范

## 1. 涉及统计与图表的问题
当用户需要比较、统计（如学历结构对比、部门人数分布等）时，
**必须**在回答末尾附上一个 ECharts 图表配置，格式如下：

```echarts
{{
  "title": {{"text": "图表标题"}},
  "tooltip": {{}},
  "legend": {{"data": ["系列名"]}},
  "xAxis": {{"type": "category", "data": ["分类1", "分类2"]}},
  "yAxis": {{"type": "value"}},
  "series": [{{"name": "系列名", "type": "bar", "data": [数值1, 数值2]}}]
}}
```

图表配置必须是合法的 JSON（不含注释），并使用最合适的图表类型（bar/pie/line 等）。

## 2. 涉及具体干部的查询
当查询结果中包含特定干部时，
**必须**在每位干部姓名后附上审批表链接，格式如下：

[查看审批表](/rag-api/v1/cadre/pdf/{{序号}})

例如：**张建国**（应用技术二部副总经理）[查看审批表](/rag-api/v1/cadre/pdf/1)

## 3. 一般问答
直接以自然语言回答，条理清晰，必要时使用表格或列表。

---

# 干部名册数据（JSON 格式，共 {count} 条）

```json
{roster}
```
"""


def _build_system_prompt() -> str:
    roster_text = _roster_as_text()
    roster = _load_roster()
    return _SYSTEM_PROMPT_TEMPLATE.format(
        count=len(roster),
        roster=roster_text,
    )


# ---------------------------------------------------------------------------
# SSE 流式生成
# ---------------------------------------------------------------------------

def _stream_cadre_chat(messages: List[Dict[str, str]]):
    """Generator: 逐 chunk yield SSE 数据，格式与 chat.py 一致。"""

    def _progress(stage: str, status: str, message: str):
        payload = {"event": "progress", "stage": stage, "status": status, "message": message}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        yield _progress("intent", "running", "准备连接模型")

        llm = _get_llm_provider()

        # 拼入系统提示词（放在 messages 首位）
        system_msg = {"role": "system", "content": _build_system_prompt()}
        full_messages = [system_msg] + [m for m in messages if m.get("role") != "system"]

        yield _progress("generation", "running", "LLM 回答生成中")

        stream = llm.client.chat.completions.create(
            model=llm.model_name,
            messages=full_messages,
            stream=True,
            temperature=0.3,
            max_tokens=llm.max_tokens,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                chunk_data = {
                    "choices": [{
                        "delta": {"content": delta.content},
                        "index": 0,
                        "finish_reason": None,
                    }]
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

        yield _progress("generation", "done", "回答生成完成")

        # 终止标记（与 chat.py 一致）
        finish_chunk = {
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}]
        }
        yield f"data: {json.dumps(finish_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as exc:
        logger.error("干部助手流式响应失败: %s", exc, exc_info=True)
        yield _progress("generation", "done", f"处理失败: {exc}")
        error_data = {"error": {"message": str(exc), "type": "internal_error"}}
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@cadre_bp.route("/v1/cadre/chat/completions", methods=["POST"])
def cadre_chat_completions():
    data = request.get_json(silent=True) or {}

    if "messages" not in data:
        return jsonify({"error": "缺少 messages 字段"}), 400

    raw_messages: List[Dict[str, str]] = []
    for msg in data["messages"]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if role in {"user", "assistant", "system"} and content:
            raw_messages.append({"role": role, "content": content})

    if not raw_messages:
        return jsonify({"error": "messages 不能为空"}), 400

    return Response(
        _stream_cadre_chat(raw_messages),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@cadre_bp.route("/v1/cadre/pdf/<int:serial_number>", methods=["GET"])
def cadre_pdf(serial_number: int):
    """
    下载/预览指定序号的任免审批表 PDF。
    PDF 文件放在  data/cadre/pdf/<序号>.pdf  目录下。
    """
    pdf_dir = _ROSTER_PATH.parent / "pdf"
    pdf_path = pdf_dir / f"{serial_number}.pdf"

    if not pdf_path.exists():
        return jsonify({
            "error": f"未找到序号 {serial_number} 的审批表 PDF（{pdf_path.name}）",
            "hint": "请将对应 PDF 放置到 data/cadre/pdf/ 目录下",
        }), 404

    return send_file(
        str(pdf_path),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"任免审批表_{serial_number}.pdf",
    )
