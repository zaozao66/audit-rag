import re
from typing import Any, Dict, List, Set, Tuple

import src.indexing.graph.ontology as ontology
from src.indexing.graph.extractors.base_extractor import BaseExtractor, RelationRecord


class AuditReportExtractor(BaseExtractor):
    REQUIREMENT_MARKERS = ("应当", "应", "需", "必须", "不得")

    TOPIC_RULES = [
        ("采购", "采购管理"),
        ("预算", "预算执行"),
        ("数据", "数据治理"),
        ("网络安全", "网络安全"),
        ("内控", "内部控制"),
        ("合规", "合规管理"),
        ("整改", "整改管理"),
    ]

    SENTENCE_SPLIT = re.compile(r"[。；;!?\n]")

    def extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        entities = self._basic_entities(doc)
        text = str(doc.get("text", ""))
        merged = self._merged_text(doc)

        for requirement in self._extract_requirements(text):
            entities.add((ontology.ENTITY_CONTROL_REQUIREMENT, requirement))

        for topic in self._extract_topics(merged):
            entities.add((ontology.ENTITY_ISSUE_TOPIC, topic))

        for amount in self._extract_amounts(merged):
            entities.add((ontology.ENTITY_AMOUNT, amount))

        return entities

    def extract_relations(self, doc: Dict[str, Any]) -> List[RelationRecord]:
        text = str(doc.get("text", ""))
        merged = self._merged_text(doc)
        relations: List[RelationRecord] = []

        requirements = self._extract_requirements(text)
        clauses = self._extract_clauses(text)
        topics = self._extract_topics(merged)
        years = self._extract_years(merged)

        for requirement in requirements:
            for clause in clauses:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_CONTROL_REQUIREMENT,
                        source_value=requirement,
                        relation=ontology.REL_RELATED_CLAUSE,
                        target_type=ontology.ENTITY_CLAUSE,
                        target_value=clause,
                        confidence=0.82,
                        weight=1.1,
                        bidirectional=True,
                        reverse_relation=ontology.REL_CLAUSE_RELATED_BY,
                    )
                )
            for risk in self._extract_risk_types(requirement):
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_CONTROL_REQUIREMENT,
                        source_value=requirement,
                        relation=ontology.REL_ADDRESSES_RISK,
                        target_type=ontology.ENTITY_RISK_TYPE,
                        target_value=risk,
                        confidence=0.75,
                        weight=1.05,
                        bidirectional=True,
                        reverse_relation=ontology.REL_RISK_ADDRESSED_BY,
                    )
                )

        for topic in topics:
            for clause in clauses:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_ISSUE_TOPIC,
                        source_value=topic,
                        relation=ontology.REL_RELATED_CLAUSE,
                        target_type=ontology.ENTITY_CLAUSE,
                        target_value=clause,
                        confidence=0.76,
                        weight=1.08,
                        bidirectional=True,
                        reverse_relation=ontology.REL_CLAUSE_RELATED_BY,
                    )
                )
            for year in years:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_ISSUE_TOPIC,
                        source_value=topic,
                        relation=ontology.REL_OCCURS_IN_YEAR,
                        target_type=ontology.ENTITY_YEAR,
                        target_value=year,
                        confidence=0.7,
                        weight=0.95,
                    )
                )

        return relations

    def _extract_requirements(self, text: str, max_items: int = 4) -> List[str]:
        candidates: List[str] = []
        for sentence in self.SENTENCE_SPLIT.split(text or ""):
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            if not any(marker in sentence for marker in self.REQUIREMENT_MARKERS):
                continue
            candidates.append(sentence[:160])
            if len(candidates) >= max_items:
                break
        return candidates

    def _extract_topics(self, text: str) -> Set[str]:
        topics = set()
        lowered = (text or "").lower()
        for kw, topic in self.TOPIC_RULES:
            if kw.lower() in lowered:
                topics.add(topic)
        return topics
