import re
from typing import Optional

import src.indexing.graph.ontology as ontology


class EntityLinker:
    """Lightweight entity normalization for graph canonical IDs."""

    DEPARTMENT_ALIAS = {
        "国家发展改革委": "国家发展和改革委员会",
        "国家发改委": "国家发展和改革委员会",
        "发改委": "国家发展和改革委员会",
        "财政部机关司局": "财政部",
        "中国人民银行": "中国人民银行",
        "央行": "中国人民银行",
    }

    def normalize(self, entity_type: str, value: str) -> Optional[str]:
        if value is None:
            return None

        text = self._normalize_whitespace(str(value))
        if not text:
            return None

        if entity_type == ontology.ENTITY_DEPARTMENT:
            text = self._normalize_department(text)
        elif entity_type == ontology.ENTITY_CLAUSE:
            text = self._normalize_clause(text)
        elif entity_type == ontology.ENTITY_AMOUNT:
            text = self._normalize_amount(text)
        elif entity_type in (
            ontology.ENTITY_ISSUE,
            ontology.ENTITY_RECT_ACTION,
            ontology.ENTITY_CONTROL_REQUIREMENT,
            ontology.ENTITY_SECTION,
        ):
            text = text[:120]
        elif entity_type == ontology.ENTITY_DOC_TYPE:
            text = text.lower()

        return text or None

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        text = text.replace("\u3000", " ")
        text = re.sub(r"\s+", " ", text).strip()
        text = text.strip("，。；;:：,./\\|[]()（）")
        return text

    def _normalize_department(self, text: str) -> str:
        text = re.sub(r"^(部门单位|部门)\s*[:：]", "", text).strip()
        text = re.sub(r"[（(].*?[）)]", "", text).strip()

        if text in self.DEPARTMENT_ALIAS:
            return self.DEPARTMENT_ALIAS[text]

        for alias, canonical in self.DEPARTMENT_ALIAS.items():
            if alias in text:
                return canonical

        return text[:60]

    @staticmethod
    def _normalize_clause(text: str) -> str:
        match = re.search(r"第[一二三四五六七八九十百千万零0-9]+条", text)
        if match:
            return match.group(0)
        return text[:40]

    @staticmethod
    def _normalize_amount(text: str) -> str:
        text = text.replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)(亿元|万元|元)", text)
        if match:
            return f"{match.group(1)}{match.group(2)}"
        return text[:40]
