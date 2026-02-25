import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

import src.indexing.graph.ontology as ontology


@dataclass
class RelationRecord:
    source_type: str
    source_value: str
    relation: str
    target_type: str
    target_value: str
    confidence: float = 0.8
    weight: float = 1.0
    bidirectional: bool = False
    reverse_relation: str = ""
    attrs: Dict[str, Any] = field(default_factory=dict)


class BaseExtractor:
    YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
    CLAUSE_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零0-9]+条")
    AMOUNT_PATTERN = re.compile(r"\d+(?:\.\d+)?(?:亿元|万元|元)")

    RISK_KEYWORDS = [
        "违规",
        "风险",
        "内控",
        "合规",
        "数据安全",
        "网络安全",
        "个人信息",
        "采购",
        "预算",
        "资金",
    ]

    def extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        return set()

    def extract_relations(self, doc: Dict[str, Any]) -> List[RelationRecord]:
        return []

    def _extract_years(self, text: str) -> Set[str]:
        return set(self.YEAR_PATTERN.findall(text or ""))

    def _extract_clauses(self, text: str, max_chars: int = 6000) -> Set[str]:
        return set(self.CLAUSE_PATTERN.findall((text or "")[:max_chars]))

    def _extract_amounts(self, text: str, max_chars: int = 4000) -> Set[str]:
        return set(self.AMOUNT_PATTERN.findall((text or "")[:max_chars]))

    def _extract_risk_types(self, text: str) -> Set[str]:
        lowered = (text or "").lower()
        result = set()
        for kw in self.RISK_KEYWORDS:
            if kw.lower() in lowered:
                result.add(kw)
        return result

    def _merged_text(self, doc: Dict[str, Any]) -> str:
        return "\n".join(
            [
                str(doc.get("title", "")),
                str(doc.get("filename", "")),
                str(doc.get("text", "")),
            ]
        )

    def _basic_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        text = str(doc.get("text", ""))
        merged = self._merged_text(doc)
        entities: Set[Tuple[str, str]] = set()

        doc_type = str(doc.get("doc_type", "")).strip()
        if doc_type:
            entities.add((ontology.ENTITY_DOC_TYPE, doc_type))

        for y in self._extract_years(merged):
            entities.add((ontology.ENTITY_YEAR, y))

        for c in self._extract_clauses(text):
            entities.add((ontology.ENTITY_CLAUSE, c))

        for r in self._extract_risk_types(merged):
            entities.add((ontology.ENTITY_RISK_TYPE, r))

        header = str(doc.get("header", "")).strip()
        if header:
            entities.add((ontology.ENTITY_SECTION, header[:80]))

        level1 = str(doc.get("level1_title", "")).strip()
        if level1:
            entities.add((ontology.ENTITY_SECTION, level1[:80]))

        level2 = str(doc.get("level2_title", "")).strip()
        if level2:
            entities.add((ontology.ENTITY_SECTION, level2[:80]))

        return entities
