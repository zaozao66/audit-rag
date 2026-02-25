"""Domain ontology constants for audit graph extraction and retrieval."""

# Entity types
ENTITY_DOCUMENT = "document"
ENTITY_CHUNK = "chunk"
ENTITY_DOC_TYPE = "doc_type"
ENTITY_YEAR = "year"
ENTITY_CLAUSE = "clause"
ENTITY_SECTION = "section"
ENTITY_DEPARTMENT = "department"
ENTITY_ISSUE_TOPIC = "issue_topic"
ENTITY_ISSUE = "issue"
ENTITY_RECT_ACTION = "rectification_action"
ENTITY_RECT_STATUS = "rectification_status"
ENTITY_CONTROL_REQUIREMENT = "control_requirement"
ENTITY_RISK_TYPE = "risk_type"
ENTITY_AMOUNT = "amount"

# Relation types
REL_CONTAINS = "contains"
REL_PART_OF = "part_of"
REL_MENTIONS = "mentions"
REL_MENTIONED_BY = "mentioned_by"

REL_BELONGS_TO_DEPARTMENT = "belongs_to_department"
REL_HAS_ISSUE = "has_issue"
REL_REQUIRES_ACTION = "requires_action"
REL_ACTION_FOR_ISSUE = "action_for_issue"
REL_HAS_STATUS = "has_status"
REL_STATUS_OF_ACTION = "status_of_action"
REL_OCCURS_IN_YEAR = "occurs_in_year"
REL_YEAR_OF_ISSUE = "year_of_issue"
REL_HAS_AMOUNT = "has_amount"
REL_AMOUNT_FOR_ISSUE = "amount_for_issue"
REL_HAS_RISK_TYPE = "has_risk_type"
REL_RISK_TYPE_OF_ISSUE = "risk_type_of_issue"

REL_RELATED_CLAUSE = "related_clause"
REL_CLAUSE_RELATED_BY = "clause_related_by"
REL_VIOLATES_CLAUSE = "violates_clause"
REL_VIOLATED_BY_ISSUE = "violated_by_issue"
REL_ADDRESSES_RISK = "addresses_risk"
REL_RISK_ADDRESSED_BY = "risk_addressed_by"

# Traversal weight by relation (for graph retrieval scoring)
RELATION_WEIGHTS = {
    REL_CONTAINS: 0.70,
    REL_PART_OF: 0.70,
    REL_MENTIONS: 0.90,
    REL_MENTIONED_BY: 0.90,
    REL_BELONGS_TO_DEPARTMENT: 1.15,
    REL_HAS_ISSUE: 1.15,
    REL_REQUIRES_ACTION: 1.20,
    REL_ACTION_FOR_ISSUE: 1.20,
    REL_HAS_STATUS: 1.00,
    REL_STATUS_OF_ACTION: 1.00,
    REL_OCCURS_IN_YEAR: 0.95,
    REL_YEAR_OF_ISSUE: 0.95,
    REL_HAS_AMOUNT: 1.00,
    REL_AMOUNT_FOR_ISSUE: 1.00,
    REL_HAS_RISK_TYPE: 1.10,
    REL_RISK_TYPE_OF_ISSUE: 1.10,
    REL_RELATED_CLAUSE: 1.12,
    REL_CLAUSE_RELATED_BY: 1.12,
    REL_VIOLATES_CLAUSE: 1.25,
    REL_VIOLATED_BY_ISSUE: 1.25,
    REL_ADDRESSES_RISK: 1.05,
    REL_RISK_ADDRESSED_BY: 1.05,
}
