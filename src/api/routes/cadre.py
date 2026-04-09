"""
干部监督智能助手路由

提供以下接口：
  POST /v1/cadre/chat/completions  — 流式对话（SSE，与 chat.py 格式一致）
  GET  /v1/cadre/roster            — 返回完整名册 JSON（供前端看板使用）
  GET  /v1/cadre/pdf/<serial>      — 下载/预览任免审批表 PDF

工作模式：工具调用（ReAct）
  LLM 不直接接收全量名册数据，而是通过调用工具在 Python 侧搜索/统计，
  将结果注入对话后再生成最终回答。这样 token 消耗与名册大小无关。
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import openai as openai_lib
from flask import Blueprint, Response, jsonify, make_response, request, send_file

from src.llm.providers.llm_provider import create_llm_provider
from src.utils.config_loader import load_config

logger = logging.getLogger(__name__)

cadre_bp = Blueprint("cadre", __name__)

# ---------------------------------------------------------------------------
# 名册数据加载（进程内缓存）
# ---------------------------------------------------------------------------

_roster_lock = threading.Lock()
_roster_cache: Optional[List[Dict[str, Any]]] = None


def _resolve_roster_path() -> Path:
    candidates = [
        Path.cwd() / "data" / "cadre" / "roster.json",
        Path(__file__).resolve().parents[3] / "data" / "cadre" / "roster.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    logger.error("roster.json 未找到，尝试路径: %s", [str(c) for c in candidates])
    return candidates[0]


_ROSTER_PATH = _resolve_roster_path()


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
            logger.info("已加载干部名册 (%s)，共 %d 条记录", _ROSTER_PATH, len(_roster_cache))
    return _roster_cache


# ---------------------------------------------------------------------------
# LLM Provider（懒加载，全局复用）
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
        llm_cfg = config.get("llm_model", {})
        provider = create_llm_provider(llm_cfg)

        # 用独立的 httpx 客户端替换默认客户端：
        #   trust_env=False       → 绕过系统代理（避免 clash/v2ray 在连接复用时 reset）
        #   retries=1             → stale 连接自动重试一次
        #   verify=False（transport 层）→ 跳过 SSL 验证（生产环境本地 CA 链不完整）
        #   注意：verify 须在 HTTPTransport 上设置，仅设在 Client 上不会传递给底层连接池
        _http = httpx.Client(
            transport=httpx.HTTPTransport(retries=1, verify=False),
            trust_env=False,
        )
        provider.client = openai_lib.OpenAI(
            api_key=provider.api_key,
            base_url=provider.endpoint,
            http_client=_http,
        )
        _llm_provider = provider
    return _llm_provider


# ---------------------------------------------------------------------------
# 工具实现（Python 侧执行，不占 LLM token）
# ---------------------------------------------------------------------------

# 家庭成员相关字段（支持父母、配偶及其他关系字段）
_FAMILY_FIELDS = [
    "父亲政治面貌", "父亲工作单位及职务",
    "母亲政治面貌", "母亲工作单位及职务",
    "配偶政治面貌", "配偶工作单位及职务",
    "家庭成员及重要社会关系",
]


def _tool_search_cadres(query: str, fields: Optional[List[str]] = None) -> List[Dict]:
    """全文搜索：在指定字段（默认全字段）中查找包含 query 的记录。"""
    q = query.strip().lower()
    results = []
    for r in _load_roster():
        if fields:
            text = " ".join(str(r.get(f, "")) for f in fields)
        else:
            text = " ".join(str(v) for v in r.values())
        if q in text.lower():
            results.append(r)
    return results


def _tool_filter_cadres(field: str, value: str) -> List[Dict]:
    """精确字段筛选（模糊匹配）。"""
    v = value.strip().lower()
    return [r for r in _load_roster() if v in str(r.get(field, "")).lower()]


def _tool_get_stats(stat_field: str, departments: Optional[List[str]] = None) -> Dict[str, int]:
    """统计指定字段的分布，可限定部门范围。"""
    subset = _load_roster()
    if departments:
        subset = [r for r in subset if r.get("部门") in departments]
    counts: Dict[str, int] = {}
    for r in subset:
        val = str(r.get(stat_field) or "未知").strip() or "未知"
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _tool_search_family(query: str) -> List[Dict]:
    """专门在家庭成员相关字段中搜索。"""
    q = query.strip().lower()
    results = []
    for r in _load_roster():
        text = " ".join(str(r.get(f, "")) for f in _FAMILY_FIELDS if r.get(f))
        if q in text.lower():
            results.append(r)
    return results


def _exec_tool(name: str, args: Dict[str, Any]) -> str:
    """执行工具调用，返回 JSON 字符串。"""
    try:
        if name == "search_cadres":
            result = _tool_search_cadres(args.get("query", ""), args.get("fields"))
        elif name == "filter_cadres":
            result = _tool_filter_cadres(args.get("field", ""), args.get("value", ""))
        elif name == "get_stats":
            result = _tool_get_stats(args.get("stat_field", ""), args.get("departments"))
        elif name == "search_family":
            result = _tool_search_family(args.get("query", ""))
        else:
            result = {"error": f"未知工具: {name}"}
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error("工具 %s 执行失败: %s", name, exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# 工具调用解析
# ---------------------------------------------------------------------------

_TOOL_RE = re.compile(
    r'\{[^{}]*"tool"\s*:\s*"([^"]+)"[^{}]*"args"\s*:\s*(\{[^}]*\})[^{}]*\}',
    re.DOTALL,
)


def _parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中提取工具调用 JSON，返回 {tool, args} 或 None。"""
    # 先尝试从 ```json ... ``` 代码块内提取
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    raw = code_block.group(1) if code_block else text.strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "tool" in obj and "args" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 正则兜底
    m = _TOOL_RE.search(text)
    if m:
        try:
            return {"tool": m.group(1), "args": json.loads(m.group(2))}
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# 系统提示词（仅描述工具，不注入数据）
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""# 角色设定
你是一名专业的干部关系审查智能助手，可以查询干部名册数据库（当前共 {{count}} 条记录）。
你不能直接看到名册数据，需要调用工具来查询。

# 工具说明
你有以下 4 个工具可以调用：

**search_cadres** — 在所有字段（或指定字段）中全文搜索
  参数：query(string), fields(string[], 可选，如["简历","现任职务"])

**filter_cadres** — 按某字段模糊匹配筛选
  参数：field(string, 如"部门"/"政治面貌"/"学历"), value(string)

**get_stats** — 统计某字段的分布（可限定部门）
  参数：stat_field(string, 如"学历"/"政治面貌"), departments(string[], 可选)

**search_family** — 专门搜索家庭成员/重要社会关系字段
  参数：query(string, 如"中共党员"/"中国能源建设")

# 调用规则
当需要查询数据时，**只输出**以下 JSON，不带任何其他文字：
```json
{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}
```
收到工具返回结果后，再根据结果给出完整回答。
可以多轮调用工具（最多 4 次），直到信息足够回答为止。

# 回答规范

## 涉及统计/图表的问题
在文字说明后**附上** ECharts 图表，格式：
```echarts
{{
  "title": {{"text": "标题", "left": "center"}},
  "tooltip": {{}},
  "legend": {{"orient": "horizontal", "bottom": 0}},
  "grid": {{"top": 60, "bottom": 60}},
  "xAxis": {{"type": "category", "data": [...]}},
  "yAxis": {{"type": "value"}},
  "series": [{{"name": "系列", "type": "bar", "data": [...]}}]
}}
```
饼图用 `"type":"pie", "radius":"60%"`；配置须为合法 JSON，不含注释。

## 涉及具体干部的查询
将干部姓名做成审批表链接：`[姓名](/rag-api/v1/cadre/pdf/{{序号}})`
例：[张建国](/rag-api/v1/cadre/pdf/1)（应用技术二部副总经理）

## 一般问答
直接用自然语言回答，可使用 Markdown 表格/列表。
"""


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT.replace("{count}", str(len(_load_roster())))


# ---------------------------------------------------------------------------
# ReAct 工具调用循环 + 流式输出
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 4


def _stream_cadre_chat(messages: List[Dict[str, str]]):
    """
    ReAct 循环：
      1. 非流式调用 LLM → 若返回工具调用则执行，追加结果后继续
      2. 得到最终文本后改为流式调用以实现打字机效果
    """

    def _sse_progress(stage: str, status: str, msg: str) -> str:
        return f"data: {json.dumps({'event':'progress','stage':stage,'status':status,'message':msg}, ensure_ascii=False)}\n\n"

    def _sse_chunk(text: str) -> str:
        return f"data: {json.dumps({'choices':[{'delta':{'content':text},'index':0,'finish_reason':None}]}, ensure_ascii=False)}\n\n"

    try:
        yield _sse_progress("intent", "running", "准备查询干部数据库")

        llm = _get_llm_provider()
        system_msg = {"role": "system", "content": _build_system_prompt()}
        conv = [system_msg] + [m for m in messages if m.get("role") != "system"]

        # ---- ReAct 工具调用轮次 ----
        for round_i in range(_MAX_TOOL_ROUNDS):
            resp = llm.client.chat.completions.create(
                model=llm.model_name,
                messages=conv,
                stream=False,
                temperature=0.1,
                max_tokens=800,   # 工具调用指令很短
            )
            assistant_text = (resp.choices[0].message.content or "").strip()

            tool_call = _parse_tool_call(assistant_text)
            if not tool_call:
                # 不是工具调用 —— 说明 LLM 准备直接回答，跳出循环
                # 把当前这次输出作为「待完善」提示，让下一轮流式生成完整回答
                # 如果它已经是完整回答就直接流式输出
                break

            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args", {})
            yield _sse_progress("retrieval", "running", f"正在执行工具：{tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

            tool_result = _exec_tool(tool_name, tool_args)

            # 尝试给出友好数量提示
            try:
                parsed = json.loads(tool_result)
                count_hint = f"返回 {len(parsed)} 条" if isinstance(parsed, list) else "执行完成"
            except Exception:
                count_hint = "执行完成"
            yield _sse_progress("retrieval", "done", f"工具 {tool_name} {count_hint}")

            # 追加工具交互到对话
            conv.append({"role": "assistant", "content": assistant_text})
            conv.append({
                "role": "user",
                "content": f"工具 {tool_name} 返回结果如下（JSON）：\n{tool_result}\n\n请继续。如需更多数据请继续调用工具，信息足够后给出完整回答。"
            })

        # ---- 流式生成最终回答 ----
        yield _sse_progress("generation", "running", "生成回答中")

        # 如果上面循环因超次退出，conv 末尾已有工具结果，直接让 LLM 汇总
        # 如果正常 break，conv 末尾是工具结果或空（直接回答的情况）
        stream = llm.client.chat.completions.create(
            model=llm.model_name,
            messages=conv,
            stream=True,
            temperature=0.3,
            max_tokens=llm.max_tokens,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield _sse_chunk(delta.content)

        yield _sse_progress("generation", "done", "回答生成完成")
        yield f"data: {json.dumps({'choices':[{'delta':{},'index':0,'finish_reason':'stop'}]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as exc:
        logger.error("干部助手流式响应失败: %s", exc, exc_info=True)
        yield _sse_progress("generation", "done", f"处理失败: {exc}")
        yield f"data: {json.dumps({'error':{'message':str(exc),'type':'internal_error'}}, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@cadre_bp.route("/v1/cadre/roster", methods=["GET"])
def cadre_roster():
    data = _load_roster()
    logger.info("cadre_roster 返回 %d 条（路径: %s）", len(data), _ROSTER_PATH)
    return jsonify(data)


@cadre_bp.route("/v1/cadre/chat/completions", methods=["POST"])
def cadre_chat_completions():
    data = request.get_json(silent=True) or {}
    if "messages" not in data:
        return jsonify({"error": "缺少 messages 字段"}), 400

    raw_messages: List[Dict[str, str]] = []
    for msg in data.get("messages", []):
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@cadre_bp.route("/v1/cadre/pdf/<int:serial_number>", methods=["GET"])
def cadre_pdf(serial_number: int):
    pdf_dir = _ROSTER_PATH.parent / "pdf"
    pdf_path = pdf_dir / f"{serial_number}.pdf"

    if not pdf_path.exists():
        html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>审批表未就绪</title>
<style>
  body{{margin:0;display:flex;align-items:center;justify-content:center;
       min-height:100vh;font-family:sans-serif;background:#f8fafc;color:#334155;}}
  .box{{text-align:center;padding:40px;border-radius:12px;
        background:#fff;border:1px solid #e2e8f0;max-width:400px;}}
  .icon{{font-size:48px;margin-bottom:16px;}}
  h2{{margin:0 0 8px;font-size:18px;color:#0f172a;}}
  p{{margin:0;font-size:13px;color:#64748b;line-height:1.6;}}
  code{{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:12px;}}
</style></head>
<body><div class="box">
  <div class="icon">📄</div>
  <h2>审批表 PDF 尚未配置</h2>
  <p>序号 <strong>{serial_number}</strong> 的任免审批表（<code>{pdf_path.name}</code>）暂未上传。<br><br>
     请将 PDF 放到 <code>data/cadre/pdf/</code> 目录下后重启服务。</p>
</div></body></html>"""
        resp = make_response(html, 404)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    return send_file(str(pdf_path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"任免审批表_{serial_number}.pdf")
