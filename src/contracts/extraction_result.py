"""Data contracts for extraction results with per-field confidence and source tracking.

These models flow through the entire pipeline — from CU extraction through
normalization, validation, and persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExtractionStage(str, Enum):
    """Pipeline stages for tracking progress."""
    INGESTED = "ingested"
    EXTRACTING = "extracting"
    AI_MAPPING = "ai_mapping"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"
    AGENT_REVIEW = "agent_review"
    PERSISTING = "persisting"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewDecision(str, Enum):
    """Routing decision based on confidence thresholds."""
    AUTO_ACCEPT = "auto_accept"
    AGENT_REVIEW = "agent_review"
    HUMAN_REVIEW = "human_review"


@dataclass
class FieldResult:
    """Per-field extraction result with confidence and provenance tracking.

    Every extracted value carries:
    - The value itself (any JSON-serializable type)
    - Confidence score (0.0–1.0) from the extraction source
    - Source attribution (which component extracted/verified it)
    - Status and optional notes for audit trail
    """
    field_path: str                          # Dot-path: "primaryMetrics.totalArea"
    value: Any = None                        # Extracted value (typed per schema)
    confidence: Optional[float] = None       # 0.0–1.0; None = unknown
    source: Optional[str] = None             # "cu", "ai_mapper", "agent", "default"
    status: str = "not_filled"               # "filled", "not_filled", "corrected"
    note: Optional[str] = None               # Audit note (e.g., "Corrected by AI mapper")

    @property
    def confidence_level(self) -> str:
        """Categorize confidence for routing decisions."""
        if self.confidence is None:
            return "unknown"
        if self.confidence >= 0.85:
            return "high"
        if self.confidence >= 0.60:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FieldResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ExtractionResult:
    """Complete extraction result for a single document.

    Aggregates all per-field results, raw responses, and pipeline metadata.
    This object flows through every pipeline stage and accumulates state.
    """
    run_id: str                                          # Unique pipeline run identifier
    source_url: str                                      # Source document URL/path
    source_hash: str                                     # SHA-256 hash for deduplication
    fields: Dict[str, FieldResult] = field(default_factory=dict)
    raw_cu_response: Optional[dict] = None               # Preserved for audit/reprocessing
    stage: ExtractionStage = ExtractionStage.INGESTED
    review_decision: Optional[ReviewDecision] = None
    errors: List[str] = field(default_factory=list)

    @property
    def fill_rate(self) -> float:
        """Percentage of fields that have a non-null value."""
        if not self.fields:
            return 0.0
        filled = sum(1 for f in self.fields.values() if f.value is not None)
        return filled / len(self.fields)

    @property
    def record_confidence(self) -> float:
        """Weighted average confidence across all filled fields."""
        filled = [f for f in self.fields.values() if f.value is not None and f.confidence is not None]
        if not filled:
            return 0.0
        return sum(f.confidence for f in filled) / len(filled)

    @property
    def low_confidence_fields(self) -> List[FieldResult]:
        """Fields with confidence below the high threshold (< 0.85)."""
        return [
            f for f in self.fields.values()
            if f.value is not None and f.confidence is not None and f.confidence < 0.85
        ]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "source_url": self.source_url,
            "source_hash": self.source_hash,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "stage": self.stage.value,
            "review_decision": self.review_decision.value if self.review_decision else None,
            "fill_rate": self.fill_rate,
            "record_confidence": self.record_confidence,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionResult:
        result = cls(
            run_id=data["run_id"],
            source_url=data["source_url"],
            source_hash=data["source_hash"],
            stage=ExtractionStage(data.get("stage", "ingested")),
        )
        for k, v in data.get("fields", {}).items():
            result.fields[k] = FieldResult.from_dict(v)
        if data.get("review_decision"):
            result.review_decision = ReviewDecision(data["review_decision"])
        return result
