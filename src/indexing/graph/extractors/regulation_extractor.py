import re
from typing import Any, Dict, List, Set, Tuple

import src.indexing.graph.ontology as ontology
from src.indexing.graph.extractors.base_extractor import BaseExtractor, RelationRecord


class RegulationExtractor(BaseExtractor):
    REQUIREMENT_MARKERS = ("应当", "应", "需", "必须", "不得", "禁止")
    SENTENCE_SPLIT = re.compile(r"[。；;!?\n]")

    def extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        entities = self._basic_entities(doc)
        text = str(doc.get("text", ""))

        for requirement in self._extract_requirements(text):
            entities.add((ontology.ENTITY_CONTROL_REQUIREMENT, requirement))

        return entities

    def extract_relations(self, doc: Dict[str, Any]) -> List[RelationRecord]:
        text = str(doc.get("text", ""))
        clauses = self._extract_clauses(text)
        requirements = self._extract_requirements(text)
        risks = self._extract_risk_types(text)

        relations: List[RelationRecord] = []

        for requirement in requirements:
            for clause in clauses:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_CONTROL_REQUIREMENT,
                        source_value=requirement,
                        relation=ontology.REL_RELATED_CLAUSE,
                        target_type=ontology.ENTITY_CLAUSE,
                        target_value=clause,
                        confidence=0.85,
                        weight=1.1,
                        bidirectional=True,
                        reverse_relation=ontology.REL_CLAUSE_RELATED_BY,
                    )
                )

            for risk in risks:
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

        for clause in clauses:
            for risk in risks:
                relations.append(
                    RelationRecord(
                        source_type=ontology.ENTITY_CLAUSE,
                        source_value=clause,
                        relation=ontology.REL_ADDRESSES_RISK,
                        target_type=ontology.ENTITY_RISK_TYPE,
                        target_value=risk,
                        confidence=0.72,
                        weight=1.05,
                        bidirectional=True,
                        reverse_relation=ontology.REL_RISK_ADDRESSED_BY,
                    )
                )

        return relations

    def _extract_requirements(self, text: str, max_items: int = 4) -> List[str]:
        items: List[str] = []
        for sentence in self.SENTENCE_SPLIT.split(text or ""):
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            if not any(marker in sentence for marker in self.REQUIREMENT_MARKERS):
                continue
            items.append(sentence[:160])
            if len(items) >= max_items:
                break
        return items
