"""
财务监督智能助手路由

提供以下接口：
  POST /caiwuassistant/chat-messages   — 流式对话（SSE，ChatGemini 兼容格式）
  GET  /gpts/detail/caiwuassistant     — 返回助手元信息

工作模式：工具调用（ReAct）
  LLM 通过工具函数在 caiwu.json 差旅数据中执行规则检查和查询，
  不将全量数据放入 prompt，token 消耗与数据量无关。

业务规则：
  1. 只有公司主要负责人（职级 B5 或 M）才能乘坐高铁一等座和飞机公务舱
  2. 出差补助金额（票据金额）= 补助天数 × 180
  3. 出差补助和打车费不能在同一次出差中同时领取
"""

import json
import logging
import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import openai as openai_lib
from flask import Blueprint, Response, jsonify, request

from src.llm.providers.llm_provider import create_llm_provider
from src.utils.config_loader import load_config

logger = logging.getLogger(__name__)

finance_bp = Blueprint("finance", __name__)

# ---------------------------------------------------------------------------
# 差旅数据加载（进程内缓存）
# ---------------------------------------------------------------------------

_data_lock = threading.Lock()
_data_cache: Optional[List[Dict[str, Any]]] = None

# 公司领导判断：所属部门为"公司领导" 且职级为"M"
_EXEC_DEPT = "公司领导"
_EXEC_LEVEL = "M"
# 每天补助标准（元）
_ALLOWANCE_PER_DAY = 180


def _resolve_data_path() -> Path:
    candidates = [
        Path.cwd() / "data" / "caiwu.json",
        Path(__file__).resolve().parents[3] / "data" / "caiwu.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    logger.error("caiwu.json 未找到，尝试路径: %s", [str(c) for c in candidates])
    return candidates[0]


_DATA_PATH = _resolve_data_path()


def _load_data() -> List[Dict[str, Any]]:
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    with _data_lock:
        if _data_cache is not None:
            return _data_cache
        try:
            with open(_DATA_PATH, encoding="utf-8") as f:
                _data_cache = json.load(f)
            logger.info("已加载差旅数据 (%s)，共 %d 条记录", _DATA_PATH, len(_data_cache))
        except Exception as exc:
            logger.error("加载差旅数据失败: %s", exc)
            _data_cache = []
    return _data_cache


# ---------------------------------------------------------------------------
# LLM 客户端（独立实例，绕过系统代理，禁用 SSL 验证）
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
# 工具实现
# ---------------------------------------------------------------------------

def _is_exec(r: Dict) -> bool:
    """判断是否为公司领导（所属部门='公司领导' 且职级='M'）。"""
    return (str(r.get("所属部门", "")).strip() == _EXEC_DEPT
            and str(r.get("职级", "")).strip() == _EXEC_LEVEL)


def _tool_check_cabin_upgrade() -> List[Dict]:
    """检查超标乘坐公务舱/一等座：非公司领导（所属部门='公司领导'且职级='M'）乘坐飞机公务舱或高铁一等座。"""
    results = []
    for r in _load_data():
        if _is_exec(r):
            continue
        cabin = str(r.get("飞机舱位", "")).strip()
        seat = str(r.get("高铁座别", "")).strip()
        violation = None
        if cabin == "飞机公务舱":
            violation = "飞机公务舱"
        elif seat == "高铁一等座":
            violation = "高铁一等座"
        if violation:
            results.append({
                "报销单编号": r.get("报销单单据编号"),
                "申请人": r.get("申请人"),
                "职级": r.get("职级"),
                "所属部门": r.get("所属部门"),
                "申请日期": r.get("申请日期"),
                "出差路线": f"{r.get('出发地')} → {r.get('目的地')}",
                "违规类型": violation,
                "票据金额": r.get("票据金额"),
            })
    return results


def _tool_check_allowance_excess() -> List[Dict]:
    """检查多领出差补助：票据金额 ≠ 补助天数 × 180。"""
    results = []
    for r in _load_data():
        if str(r.get("差旅费类型", "")).strip() != "出差补助":
            continue
        try:
            days = float(r.get("补助天数") or 0)
            amount = float(r.get("票据金额") or 0)
        except (TypeError, ValueError):
            continue
        expected = days * _ALLOWANCE_PER_DAY
        if abs(amount - expected) > 0.5:
            results.append({
                "报销单编号": r.get("报销单单据编号"),
                "申请人": r.get("申请人"),
                "职级": r.get("职级"),
                "所属部门": r.get("所属部门"),
                "申请日期": r.get("申请日期"),
                "出差路线": f"{r.get('出发地')} → {r.get('目的地')}",
                "补助天数": days,
                "应领金额": expected,
                "实领金额": amount,
                "差额": round(amount - expected, 2),
            })
    return results


def _tool_check_double_claim() -> List[Dict]:
    """检查同一出差中既领出差补助又领打车费。"""
    # 按（申请人，出差开始日期，出差结束日期）分组
    by_trip: Dict[tuple, List[Dict]] = defaultdict(list)
    for r in _load_data():
        key = (
            str(r.get("申请人", "")).strip(),
            str(r.get("出差开始日期", "")).strip(),
            str(r.get("出差结束日期", "")).strip(),
        )
        if any(k == "" for k in key):
            continue
        by_trip[key].append(r)

    results = []
    for (person, start, end), records in by_trip.items():
        types = {str(r.get("差旅费类型", "")).strip() for r in records}
        if "出差补助" in types and "其他（打车费）" in types:
            results.append({
                "申请人": person,
                "出差开始日期": start,
                "出差结束日期": end,
                "所属部门": records[0].get("所属部门"),
                "出差路线": f"{records[0].get('出发地')} → {records[0].get('目的地')}",
                "补助金额": next((r.get("票据金额") for r in records if r.get("差旅费类型") == "出差补助"), None),
                "打车费金额": next((r.get("票据金额") for r in records if r.get("差旅费类型") == "其他（打车费）"), None),
            })
    return results


def _tool_search_records(field: str, value: str) -> List[Dict]:
    """按字段值模糊搜索差旅记录。"""
    v = value.strip().lower()
    return [r for r in _load_data() if v in str(r.get(field, "")).lower()]


def _tool_get_stats(group_by: str, filter_field: str = "", filter_value: str = "") -> Dict[str, int]:
    """统计指定字段的分布，可按另一字段值过滤。"""
    subset = _load_data()
    if filter_field and filter_value:
        subset = [r for r in subset if filter_value.lower() in str(r.get(filter_field, "")).lower()]
    counts: Dict[str, int] = {}
    for r in subset:
        val = str(r.get(group_by) or "未知").strip() or "未知"
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _exec_tool(name: str, args: Dict[str, Any]) -> str:
    try:
        if name == "check_cabin_upgrade":
            result = _tool_check_cabin_upgrade()
        elif name == "check_allowance_excess":
            result = _tool_check_allowance_excess()
        elif name == "check_double_claim":
            result = _tool_check_double_claim()
        elif name == "search_records":
            result = _tool_search_records(args.get("field", ""), args.get("value", ""))
        elif name == "get_stats":
            result = _tool_get_stats(
                args.get("group_by", ""),
                args.get("filter_field", ""),
                args.get("filter_value", ""),
            )
        else:
            result = {"error": f"未知工具: {name}"}
        # 限制返回条数避免 token 超限
        if isinstance(result, list) and len(result) > 100:
            summary = {"总计": len(result), "前100条": result[:100]}
            return json.dumps(summary, ensure_ascii=False)
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
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    raw = code_block.group(1) if code_block else text.strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "tool" in obj and "args" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    m = _TOOL_RE.search(text)
    if m:
        try:
            return {"tool": m.group(1), "args": json.loads(m.group(2))}
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一名专业的财务监督智能助手，负责审查公司差旅费报销数据，发现违规行为。

当前数据库共有 {count} 条差旅费记录，包含字段：
报销单单据编号、申请单单据编号、申请日期、申请部门/团队、所属部门、申请人、
核定付款金额汇总、职级、差旅费类型、出差开始日期、出差结束日期、出发地、目的地、
出差天数、住宿天数、补助天数、票据金额、付款的金额、飞机舱位、高铁座别、火车席别、轮船舱位、住宿类别

差旅费类型包括：住宿费、飞机票、高铁票、火车票、出差补助、其他（打车费）、其他费用
飞机舱位：飞机经济舱、飞机公务舱
高铁座别：高铁二等座、高铁一等座

## 业务规则（重要）
1. 只有公司领导（所属部门为"公司领导"且职级为"M"）才能乘坐高铁一等座和飞机公务舱，其他人员不允许
2. 出差补助金额（票据金额）必须等于 补助天数 × 180 元，不得多报少报
3. 出差补助和打车费（其他（打车费））不能在同一次出差中同时报销

## 可用工具
当需要查询数据时，输出以下 JSON 格式（严格 JSON，无其他内容）：
{"tool": "<工具名>", "args": {<参数>}}

工具列表：
- check_cabin_upgrade：{}  检查所有超标乘坐公务舱/一等座的记录（非公司领导人员）
- check_allowance_excess：{}  检查所有出差补助金额不符合规定的记录
- check_double_claim：{}  检查所有同一出差中既领补助又领打车费的记录
- search_records：{"field": "字段名", "value": "搜索值"}  按字段值模糊搜索
- get_stats：{"group_by": "字段名", "filter_field": "过滤字段（可选）", "filter_value": "过滤值（可选）"}  统计分布

## 输出要求
- 如果需要调用工具，只输出工具调用 JSON，不附加任何其他文字
- 如果不需要调用工具，直接用中文回答
- 最终回答要结构清晰，用 Markdown 格式，数字结论要明确
- 列举违规记录时，给出关键信息（申请人、部门、日期、金额、违规类型）
"""

_MAX_TOOL_ROUNDS = 4

# ---------------------------------------------------------------------------
# 核心：ReAct 流式对话
# ---------------------------------------------------------------------------

def _stream_finance_chat(messages: List[Dict[str, str]]):
    """ReAct 工具调用循环 + 流式最终回答，生成 OpenAI SSE 行迭代器。"""

    def _sse(content: str) -> str:
        payload = json.dumps(
            {"choices": [{"delta": {"content": content}}]},
            ensure_ascii=False,
        )
        return f"data: {payload}\n\n"

    try:
        llm = _get_llm_provider()
    except Exception as exc:
        logger.error("获取 LLM 失败: %s", exc)
        yield _sse(f"[错误] 无法连接 AI 服务：{exc}")
        return

    system_prompt = _SYSTEM_PROMPT.replace("{count}", str(len(_load_data())))
    conv = [{"role": "system", "content": system_prompt}] + list(messages)

    # --- ReAct 工具调用轮次 ---
    for round_i in range(_MAX_TOOL_ROUNDS):
        try:
            resp = llm.client.chat.completions.create(
                model=llm.model_name,
                messages=conv,
                stream=False,
                max_tokens=1000,
                temperature=0.2,
            )
        except Exception as exc:
            logger.error("财务助手非流式请求失败 [%d]: %s", round_i + 1, exc)
            yield _sse(f"[错误] AI 服务请求失败：{exc}")
            return

        assistant_text = (resp.choices[0].message.content or "").strip()
        tool_call = _parse_tool_call(assistant_text)

        if not tool_call:
            break  # 没有工具调用，进入流式回答阶段

        tool_name = tool_call.get("tool", "")
        tool_args = tool_call.get("args", {})
        logger.info("财务助手工具调用 [round %d]: %s %s", round_i + 1, tool_name, tool_args)
        tool_result = _exec_tool(tool_name, tool_args)

        conv.append({"role": "assistant", "content": assistant_text})
        conv.append({
            "role": "user",
            "content": f"工具 {tool_name} 返回结果：\n{tool_result}\n\n请根据以上数据继续分析，如需更多数据可继续调用工具，否则直接给出最终回答。",
        })
    else:
        conv.append({"role": "user", "content": "请根据已有数据给出最终分析结论。"})

    # --- 流式最终回答 ---
    try:
        stream = llm.client.chat.completions.create(
            model=llm.model_name,
            messages=conv,
            stream=True,
            max_tokens=2000,
            temperature=0.3,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield _sse(delta)
        yield "data: [DONE]\n\n"

    except Exception as exc:
        logger.error("财务助手流式响应失败: %s", exc, exc_info=True)
        yield _sse(f"\n\n[错误] 流式响应异常：{exc}")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@finance_bp.route("/v1/finance/chat/completions", methods=["POST"])
def finance_chat():
    """财务助手流式对话接口（OpenAI SSE 格式，与 cadre 一致）。"""
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])

    if not messages:
        return jsonify({"error": "messages 不能为空"}), 400

    def generate():
        for line in _stream_finance_chat(messages):
            yield line

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
