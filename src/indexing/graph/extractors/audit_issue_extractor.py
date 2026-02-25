import re
from typing import Any, Dict, List, Set, Tuple

import src.indexing.graph.ontology as ontology
from src.indexing.graph.extractors.base_extractor import BaseExtractor, RelationRecord


class AuditIssueExtractor(BaseExtractor):
    DEPT_PATTERN = re.compile(r"(?:部门单位|部门)\s*[:：]\s*([^\n]{2,80})")
    ISSUE_PATTERN = re.compile(r"(?:问题摘要|问题描述)\s*[:：]\s*([^\n]{4,220})")
    ACTION_PATTERN = re.compile(r"(?:整改情况|整改措施|整改结果)\s*[:：]\s*([^\n]{4,240})")

    STATUS_RULES = {
        "已整改": "completed",
        "整改完成": "completed",
        "完成整改": "completed",
        "持续整改": "in_progress",
        "正在整改": "in_progress",
        "推进整改": "in_progress",
        "未整改": "pending",
        "尚未整改": "pending",
        "待整改": "pending",
    }

    TOPIC_RULES = [
        ("采购", "采购管理"),
        ("预算", "预算执行"),
        ("资金", "资金管理"),
        ("数据", "数据治理"),
        ("网络", "网络安全"),
        ("内控", "内部控制"),
        ("个人信息", "个人信息保护"),
        ("项目", "项目管理"),
    ]

    def extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        entities = self._basic_entities(doc)
        text = str(doc.get("text", ""))
        merged = self._merged_text(doc)

        for dept in self.DEPT_PATTERN.findall(text[:5000]):
            value = dept.strip()
            if value:
                entities.add((ontology.ENTITY_DEPARTMENT, value[:80]))

        issue_text = self._extract_issue(text)
        if issue_text:
            entities.add((ontology.ENTITY_ISSUE, issue_text))

        action_text = self._extract_action(text)
        if action_text:
            entities.add((ontology.ENTITY_RECT_ACTION, action_text))

        status = self._extract_status(text)
        if status:
            entities.add((ontology.ENTITY_RECT_STATUS, status))

        for amount in self._extract_amounts(merged):
            entities.add((ontology.ENTITY_AMOUNT, amount))

        for topic in self._extract_topics(merged):
            entities.add((ontology.ENTITY_ISSUE_TOPIC, topic))

        return entities

    def extract_relations(self, doc: Dict[str, Any]) -> List[RelationRecord]:
        text = str(doc.get("text", ""))
        merged = self._merged_text(doc)
        relations: List[RelationRecord] = []

        issue = self._extract_issue(text)
        if not issue:
            return relations

        for dept in self.DEPT_PATTERN.findall(text[:5000]):
            value = dept.strip()
            if not value:
                continue
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_BELONGS_TO_DEPARTMENT,
                    target_type=ontology.ENTITY_DEPARTMENT,
                    target_value=value,
                    confidence=0.95,
                    weight=1.2,
                    bidirectional=True,
                    reverse_relation=ontology.REL_HAS_ISSUE,
                )
            )

        action = self._extract_action(text)
        if action:
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_REQUIRES_ACTION,
                    target_type=ontology.ENTITY_RECT_ACTION,
                    target_value=action,
                    confidence=0.9,
                    weight=1.2,
                    bidirectional=True,
                    reverse_relation=ontology.REL_ACTION_FOR_ISSUE,
                )
            )

            status = self._extract_status(text)
            if status:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_RECT_ACTION,
                        source_value=action,
                        relation=ontology.REL_HAS_STATUS,
                        target_type=ontology.ENTITY_RECT_STATUS,
                        target_value=status,
                        confidence=0.88,
                        weight=1.0,
                        bidirectional=True,
                        reverse_relation=ontology.REL_STATUS_OF_ACTION,
                    )
                )

        for clause in self._extract_clauses(text):
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_VIOLATES_CLAUSE,
                    target_type=ontology.ENTITY_CLAUSE,
                    target_value=clause,
                    confidence=0.86,
                    weight=1.25,
                    bidirectional=True,
                    reverse_relation=ontology.REL_VIOLATED_BY_ISSUE,
                )
            )

        for year in self._extract_years(merged):
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_OCCURS_IN_YEAR,
                    target_type=ontology.ENTITY_YEAR,
                    target_value=year,
                    confidence=0.8,
                    weight=0.95,
                    bidirectional=True,
                    reverse_relation=ontology.REL_YEAR_OF_ISSUE,
                )
            )

        for amount in self._extract_amounts(merged):
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_HAS_AMOUNT,
                    target_type=ontology.ENTITY_AMOUNT,
                    target_value=amount,
                    confidence=0.82,
                    weight=1.0,
                    bidirectional=True,
                    reverse_relation=ontology.REL_AMOUNT_FOR_ISSUE,
                )
            )

        for risk in self._extract_risk_types(merged):
            relations.append(
                RelationRecord(
                    source_type=ontology.ENTITY_ISSUE,
                    source_value=issue,
                    relation=ontology.REL_HAS_RISK_TYPE,
                    target_type=ontology.ENTITY_RISK_TYPE,
                    target_value=risk,
                    confidence=0.78,
                    weight=1.1,
                    bidirectional=True,
                    reverse_relation=ontology.REL_RISK_TYPE_OF_ISSUE,
                )
            )

        return relations

    def _extract_issue(self, text: str) -> str:
        match = self.ISSUE_PATTERN.search(text)
        if match:
            return match.group(1).strip()[:160]
        # fallback:取第一段代表问题描述
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in lines:
            if len(line) >= 12 and ("问题" in line or "违规" in line or "整改" in line):
                return line[:160]
        return ""

    def _extract_action(self, text: str) -> str:
        match = self.ACTION_PATTERN.search(text)
        if match:
            return match.group(1).strip()[:160]
        return ""

    def _extract_status(self, text: str) -> str:
        sample = text[:1500]
        for key, val in self.STATUS_RULES.items():
            if key in sample:
                return val
        return ""

    def _extract_topics(self, text: str) -> Set[str]:
        topics = set()
        lowered = text.lower()
        for kw, topic in self.TOPIC_RULES:
            if kw.lower() in lowered:
                topics.add(topic)
        return topics
