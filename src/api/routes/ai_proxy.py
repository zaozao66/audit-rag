import json
import os
import re
from typing import Any, Dict, List

import httpx
from flask import Blueprint, current_app, jsonify, request
from openai import OpenAI

from src.utils.config_loader import load_config


ai_proxy_bp = Blueprint("ai_proxy", __name__)


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _to_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _join_url(base_url: str, path: str) -> str:
    return f"{str(base_url or '').rstrip('/')}/{str(path or '').lstrip('/')}"


def _resolve_asr_config() -> Dict[str, Any]:
    config = load_config()
    llm_config = config.get("llm_model", {}) if isinstance(config.get("llm_model"), dict) else {}
    asr_config = config.get("asr_proxy", {}) if isinstance(config.get("asr_proxy"), dict) else {}

    endpoint = str(
        os.getenv("ASR_PROXY_ENDPOINT")
        or asr_config.get("endpoint")
        or llm_config.get("endpoint")
        or ""
    ).strip()
    api_key = str(
        os.getenv("ASR_PROXY_API_KEY")
        or asr_config.get("api_key")
        or llm_config.get("api_key")
        or ""
    ).strip()
    model_name = str(
        os.getenv("ASR_PROXY_MODEL")
        or asr_config.get("model_name")
        or "qwen3-asr"
    ).strip()
    api_path = str(
        os.getenv("ASR_PROXY_PATH")
        or asr_config.get("path")
        or "/audio/transcriptions"
    ).strip()
    request_timeout = _to_float(
        os.getenv("ASR_PROXY_TIMEOUT")
        or asr_config.get("request_timeout"),
        60.0,
    )
    ssl_verify = _to_bool(
        os.getenv("ASR_PROXY_SSL_VERIFY")
        if os.getenv("ASR_PROXY_SSL_VERIFY") is not None
        else asr_config.get("ssl_verify"),
        default=bool(llm_config.get("ssl_verify", True)),
    )

    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model_name": model_name,
        "api_path": api_path,
        "request_timeout": request_timeout,
        "ssl_verify": ssl_verify,
    }


def _resolve_department_ai_config() -> Dict[str, Any]:
    config = load_config()
    llm_config = config.get("llm_model", {}) if isinstance(config.get("llm_model"), dict) else {}
    portrait_config = (
        config.get("department_portrait_ai", {})
        if isinstance(config.get("department_portrait_ai"), dict)
        else {}
    )

    endpoint = str(
        os.getenv("DEPARTMENT_AI_ENDPOINT")
        or portrait_config.get("endpoint")
        or llm_config.get("endpoint")
        or ""
    ).strip()
    api_key = str(
        os.getenv("DEPARTMENT_AI_API_KEY")
        or portrait_config.get("api_key")
        or llm_config.get("api_key")
        or ""
    ).strip()
    model_name = str(
        os.getenv("DEPARTMENT_AI_MODEL")
        or portrait_config.get("model_name")
        or llm_config.get("model_name")
        or "GLM-4.7-W8A8"
    ).strip()
    request_timeout = _to_float(
        os.getenv("DEPARTMENT_AI_TIMEOUT")
        or portrait_config.get("request_timeout")
        or llm_config.get("request_timeout"),
        60.0,
    )
    max_tokens = _to_int(
        os.getenv("DEPARTMENT_AI_MAX_TOKENS")
        or portrait_config.get("max_tokens")
        or llm_config.get("max_tokens"),
        1200,
    )
    temperature = _to_float(
        os.getenv("DEPARTMENT_AI_TEMPERATURE")
        or portrait_config.get("temperature")
        or llm_config.get("temperature"),
        0.3,
    )
    ssl_verify = _to_bool(
        os.getenv("DEPARTMENT_AI_SSL_VERIFY")
        if os.getenv("DEPARTMENT_AI_SSL_VERIFY") is not None
        else portrait_config.get("ssl_verify"),
        default=bool(llm_config.get("ssl_verify", True)),
    )

    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model_name": model_name,
        "request_timeout": request_timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "ssl_verify": ssl_verify,
    }


def _extract_json_block(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}

    if text.startswith("```json"):
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _build_fallback_department_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    department_name = str(data.get("department_name") or "该部门")
    personnel_total = int(data.get("personnel_total") or 0)
    travel_expense = float(data.get("travel_expense") or 0)
    audit_issues = int(data.get("audit_issues") or 0)
    audit_completed = int(data.get("audit_completed") or 0)
    completion_rate = float(data.get("audit_completion_rate") or 0)
    risk_high = int(data.get("risk_high") or 0)
    risk_medium = int(data.get("risk_medium") or 0)
    risk_low = int(data.get("risk_low") or 0)
    risk_total = int(data.get("risk_total") or (risk_high + risk_medium + risk_low))

    return {
        "overall_judgement": f"{department_name}整体监督态势总体平稳，重点风险集中在审计问题闭环与高风险岗位管控。",
        "personnel_insight": f"人员规模为{personnel_total}人，建议持续关注人员结构变化带来的岗位职责调整风险。",
        "finance_insight": f"年度差旅报销金额约{travel_expense:.1f}万元，建议结合预算执行节奏开展月度对标复盘。",
        "audit_insight": (
            f"审计问题{audit_issues}项，已完成{audit_completed}项，完成率{completion_rate:.1f}%。"
            "建议对未完成事项逐条明确责任人与时限。"
        ),
        "risk_insight": (
            f"岗位廉政风险共{risk_total}项，其中高风险{risk_high}项、中风险{risk_medium}项、低风险{risk_low}项，"
            "应优先围绕高风险岗位完善双人复核与关键节点留痕机制。"
        ),
        "cross_risk_hint": "从跨维度看，审计问题整改进度与岗位风险治理强相关，建议同步推进制度约束与流程优化。",
        "recommendations": [
            "建立问题整改周跟踪机制，对逾期事项自动预警并滚动通报。",
            "针对高风险岗位开展分层分级复盘，形成年度风险控制清单。",
            "将财务波动与审计问题类型联动分析，提前识别趋势性风险。",
        ],
        "conclusion": "建议持续保持“数据监测 + 问题闭环 + 风险治理”协同推进，稳步提升部门监督质效。",
        "fallback": True,
    }


def _normalize_department_analysis(result: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(fallback)
    if not isinstance(result, dict):
        return normalized

    for key in [
        "overall_judgement",
        "personnel_insight",
        "finance_insight",
        "audit_insight",
        "risk_insight",
        "cross_risk_hint",
        "conclusion",
    ]:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()

    recommendations = result.get("recommendations")
    if isinstance(recommendations, list):
        cleaned: List[str] = []
        for item in recommendations:
            item_text = str(item or "").strip()
            if item_text:
                cleaned.append(item_text)
        if cleaned:
            normalized["recommendations"] = cleaned[:5]

    normalized["fallback"] = bool(result.get("fallback", False))
    return normalized


def _build_department_analysis_prompt(data: Dict[str, Any]) -> str:
    compact_payload = json.dumps(data, ensure_ascii=False)
    return (
        "你是金融监督场景的高级分析助手。请严格基于输入数据生成“部门监督画像”分析结论，"
        "不允许编造数字。输出必须为JSON对象，字段如下：\n"
        "{\n"
        "  \"overall_judgement\": \"综合判断\",\n"
        "  \"personnel_insight\": \"人员情况分析\",\n"
        "  \"finance_insight\": \"财务情况分析\",\n"
        "  \"audit_insight\": \"纪审联动分析\",\n"
        "  \"risk_insight\": \"岗位廉政风险分析\",\n"
        "  \"cross_risk_hint\": \"跨维度风险提示\",\n"
        "  \"recommendations\": [\"建议1\", \"建议2\", \"建议3\"],\n"
        "  \"conclusion\": \"总结建议\"\n"
        "}\n"
        "写作要求：\n"
        "1) 语言正式、适合领导阅览；\n"
        "2) 结论明确且可执行；\n"
        "3) 若数据不足请明确说明，不得补造事实。\n\n"
        f"输入数据：{compact_payload}"
    )


@ai_proxy_bp.route("/v1/audio/transcriptions", methods=["POST"])
def proxy_audio_transcriptions():
    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        return jsonify({"error": "缺少file文件参数"}), 400

    file_bytes = uploaded_file.read()
    if not file_bytes:
        return jsonify({"error": "上传音频为空"}), 400

    asr_config = _resolve_asr_config()
    if not asr_config.get("endpoint"):
        return jsonify({"error": "ASR代理未配置endpoint"}), 500
    if not asr_config.get("api_key"):
        return jsonify({"error": "ASR代理未配置api_key"}), 500

    upstream_url = _join_url(asr_config["endpoint"], asr_config["api_path"])
    form_data: Dict[str, Any] = {}
    for key in ["model", "language", "prompt", "response_format", "temperature"]:
        value = request.form.get(key)
        if value is not None and str(value).strip():
            form_data[key] = str(value).strip()

    if "model" not in form_data and asr_config.get("model_name"):
        form_data["model"] = asr_config["model_name"]

    headers = {"Authorization": f"Bearer {asr_config['api_key']}"}
    files = {
        "file": (
            uploaded_file.filename or "audio.wav",
            file_bytes,
            uploaded_file.mimetype or "application/octet-stream",
        )
    }

    try:
        with httpx.Client(
            verify=asr_config["ssl_verify"],
            timeout=asr_config["request_timeout"],
            trust_env=False,
        ) as client:
            upstream_response = client.post(
                upstream_url,
                headers=headers,
                data=form_data,
                files=files,
            )
    except httpx.TimeoutException:
        return jsonify({"error": "ASR上游请求超时"}), 504
    except Exception as exc:
        current_app.logger.error("ASR代理请求失败: %s", exc)
        return jsonify({"error": f"ASR代理请求失败: {exc}"}), 502

    content_type = (upstream_response.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            return jsonify(upstream_response.json()), upstream_response.status_code
        except Exception:
            pass

    return (
        upstream_response.text,
        upstream_response.status_code,
        {"Content-Type": content_type or "text/plain; charset=utf-8"},
    )


@ai_proxy_bp.route("/reports/department-portrait/analysis", methods=["POST"])
def generate_department_portrait_analysis():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "请求体必须为JSON对象"}), 400

    fallback_analysis = _build_fallback_department_analysis(payload)
    ai_config = _resolve_department_ai_config()

    if not ai_config.get("endpoint") or not ai_config.get("api_key"):
        return jsonify(
            {
                "success": True,
                "analysis": fallback_analysis,
                "warning": "未配置department_portrait_ai模型参数，已降级为规则分析",
            }
        )

    http_client = httpx.Client(
        verify=ai_config["ssl_verify"],
        timeout=ai_config["request_timeout"],
        trust_env=False,
    )
    model_client = OpenAI(
        api_key=ai_config["api_key"],
        base_url=ai_config["endpoint"],
        http_client=http_client,
    )
    prompt = _build_department_analysis_prompt(payload)

    try:
        response = model_client.chat.completions.create(
            model=ai_config["model_name"],
            messages=[
                {"role": "system", "content": "你是审慎、客观、严谨的监督分析助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=ai_config["temperature"],
            max_tokens=ai_config["max_tokens"],
            timeout=ai_config["request_timeout"],
        )
        content = (response.choices[0].message.content or "").strip()
        parsed = _extract_json_block(content)
        analysis = _normalize_department_analysis(parsed, fallback_analysis)
        if not parsed:
            analysis["fallback"] = True

        return jsonify(
            {
                "success": True,
                "analysis": analysis,
                "model": ai_config["model_name"],
            }
        )
    except Exception as exc:
        current_app.logger.error("部门监督画像AI分析失败，使用回退方案: %s", exc)
        return jsonify(
            {
                "success": True,
                "analysis": fallback_analysis,
                "warning": f"模型分析失败，已使用规则分析: {exc}",
            }
        )
    finally:
        close_method = getattr(model_client, "close", None)
        if callable(close_method):
            close_method()
        http_client.close()
