"""Human-readable labels for graph entities and relations."""

from typing import Dict

import src.indexing.graph.ontology as ontology


ENTITY_TYPE_LABELS: Dict[str, str] = {
    ontology.ENTITY_DOCUMENT: "文档",
    ontology.ENTITY_CHUNK: "分块",
    ontology.ENTITY_DOC_TYPE: "文档类型",
    ontology.ENTITY_YEAR: "年份",
    ontology.ENTITY_CLAUSE: "条款",
    ontology.ENTITY_SECTION: "章节",
    ontology.ENTITY_DEPARTMENT: "部门",
    ontology.ENTITY_ISSUE_TOPIC: "问题主题",
    ontology.ENTITY_ISSUE: "问题",
    ontology.ENTITY_RECT_ACTION: "整改措施",
    ontology.ENTITY_RECT_STATUS: "整改状态",
    ontology.ENTITY_CONTROL_REQUIREMENT: "管控要求",
    ontology.ENTITY_RISK_TYPE: "风险类型",
    ontology.ENTITY_AMOUNT: "金额",
}

RELATION_LABELS: Dict[str, str] = {
    ontology.REL_CONTAINS: "包含",
    ontology.REL_PART_OF: "属于",
    ontology.REL_MENTIONS: "提及",
    ontology.REL_MENTIONED_BY: "被提及于",
    ontology.REL_BELONGS_TO_DEPARTMENT: "归属部门",
    ontology.REL_HAS_ISSUE: "有问题",
    ontology.REL_REQUIRES_ACTION: "需要整改措施",
    ontology.REL_ACTION_FOR_ISSUE: "措施对应问题",
    ontology.REL_HAS_STATUS: "具有状态",
    ontology.REL_STATUS_OF_ACTION: "状态对应措施",
    ontology.REL_OCCURS_IN_YEAR: "发生于年份",
    ontology.REL_YEAR_OF_ISSUE: "年份对应问题",
    ontology.REL_HAS_AMOUNT: "涉及金额",
    ontology.REL_AMOUNT_FOR_ISSUE: "金额对应问题",
    ontology.REL_HAS_RISK_TYPE: "涉及风险类型",
    ontology.REL_RISK_TYPE_OF_ISSUE: "风险类型对应问题",
    ontology.REL_RELATED_CLAUSE: "关联条款",
    ontology.REL_CLAUSE_RELATED_BY: "被关联条款",
    ontology.REL_VIOLATES_CLAUSE: "违反条款",
    ontology.REL_VIOLATED_BY_ISSUE: "被问题违反",
    ontology.REL_ADDRESSES_RISK: "应对风险",
    ontology.REL_RISK_ADDRESSED_BY: "被用于应对风险",
}

DOC_TYPE_LABELS: Dict[str, str] = {
    "internal_regulation": "内部制度",
    "external_regulation": "外部法规",
    "internal_report": "内部审计报告",
    "external_report": "外部审计报告",
    "audit_issue": "审计问题整改",
    "unknown": "未知类型",
}

_ENTITY_LABEL_TO_KEY = {v: k for k, v in ENTITY_TYPE_LABELS.items()}
_RELATION_LABEL_TO_KEY = {v: k for k, v in RELATION_LABELS.items()}


def entity_type_label(entity_type: str) -> str:
    return ENTITY_TYPE_LABELS.get(entity_type, entity_type or "")


def relation_label(relation: str) -> str:
    return RELATION_LABELS.get(relation, relation or "")


def doc_type_label(doc_type: str) -> str:
    return DOC_TYPE_LABELS.get(doc_type, doc_type or "")


def entity_type_key(value: str) -> str:
    if not value:
        return ""
    return _ENTITY_LABEL_TO_KEY.get(value, value)


def relation_key(value: str) -> str:
    if not value:
        return ""
    return _RELATION_LABEL_TO_KEY.get(value, value)

