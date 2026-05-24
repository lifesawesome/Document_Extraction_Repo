"""Validator — business rules, cross-field consistency checks, and routing decision.

Runs AFTER normalization. Validates extracted data against:
1. Range rules (values within expected bounds)
2. Required field checks (critical fields must be present)
3. Cross-field consistency (related fields must be logically consistent)
4. Confidence-based routing decision (auto-accept / agent-review / human-review)

CUSTOMIZATION POINT: Define your domain-specific validation rules in RANGE_RULES,
REQUIRED_FIELDS, and _cross_field_checks().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.config import PipelineConfig
from src.contracts.extraction_result import ExtractionResult, FieldResult, ReviewDecision

logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOMIZATION POINT: Range Rules
# =============================================================================
# Define acceptable ranges for numeric fields.
# Key = dot-path, Value = (min, max)
# Fields outside these ranges get confidence penalties.

RANGE_RULES: Dict[str, Tuple[float, float]] = {
    "primaryMetrics.totalArea": (100, 50_000),
    "primaryMetrics.conditionedArea": (100, 50_000),
    "primaryMetrics.secondaryArea": (0, 30_000),
    "primaryMetrics.auxiliaryArea": (0, 10_000),
    "primaryMetrics.stories": (1, 5),
    "structuralDetails.primaryRooms": (1, 20),
    "structuralDetails.secondaryRooms": (1, 15),
    # Add your domain-specific range rules here...
}

# =============================================================================
# CUSTOMIZATION POINT: Required Fields
# =============================================================================
# Fields that MUST be present for a valid extraction.
# Missing required fields lower record confidence significantly.

REQUIRED_FIELDS: List[str] = [
    "documentInfo.documentNumber",
    "primaryMetrics.totalArea",
    "primaryMetrics.conditionedArea",
    "primaryMetrics.stories",
    "structuralDetails.primaryRooms",
    "structuralDetails.secondaryRooms",
    # Add your domain-specific required fields here...
]


@dataclass
class ValidationViolation:
    """A single validation rule violation."""
    field_path: str
    rule: str
    message: str
    severity: str = "warning"  # "warning" or "error"
    confidence_penalty: float = 0.0


class Validator:
    """Validates extraction results against business rules and determines routing."""

    # Confidence penalty amounts
    _RANGE_PENALTY = 0.20
    _REQUIRED_PENALTY = 0.25
    _CONSISTENCY_PENALTY = 0.15

    def __init__(self, config: PipelineConfig):
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate(self, extraction: ExtractionResult) -> Tuple[ExtractionResult, List[ValidationViolation]]:
        """Run all validation rules and determine routing decision.

        Returns:
            Tuple of (updated ExtractionResult with penalties applied, list of violations).
        """
        violations: List[ValidationViolation] = []

        # 1. Range checks
        violations.extend(self._check_ranges(extraction))

        # 2. Required field checks
        violations.extend(self._check_required(extraction))

        # 3. Cross-field consistency
        violations.extend(self._cross_field_checks(extraction))

        # Apply confidence penalties
        for v in violations:
            if v.confidence_penalty > 0 and v.field_path in extraction.fields:
                field = extraction.fields[v.field_path]
                if field.confidence is not None:
                    field.confidence = max(0.0, field.confidence - v.confidence_penalty)
                    field.note = (field.note or "") + f" | Validation: {v.message}"

        # 4. Determine routing decision
        extraction.review_decision = self._routing_decision(extraction)

        logger.info(
            "Validator: %d violations, record_confidence=%.2f, decision=%s for run %s",
            len(violations), extraction.record_confidence,
            extraction.review_decision.value, extraction.run_id,
        )

        return extraction, violations

    # ------------------------------------------------------------------
    # Range validation
    # ------------------------------------------------------------------
    def _check_ranges(self, extraction: ExtractionResult) -> List[ValidationViolation]:
        """Check numeric fields are within expected bounds."""
        violations = []
        for dot_path, (min_val, max_val) in RANGE_RULES.items():
            field = extraction.fields.get(dot_path)
            if not field or field.value is None:
                continue

            try:
                val = float(field.value)
            except (TypeError, ValueError):
                continue

            if val < min_val or val > max_val:
                violations.append(ValidationViolation(
                    field_path=dot_path,
                    rule="range",
                    message=f"{dot_path}={val} outside range [{min_val}, {max_val}]",
                    severity="warning",
                    confidence_penalty=self._RANGE_PENALTY,
                ))

        return violations

    # ------------------------------------------------------------------
    # Required field checks
    # ------------------------------------------------------------------
    def _check_required(self, extraction: ExtractionResult) -> List[ValidationViolation]:
        """Check that required fields have values."""
        violations = []
        for dot_path in REQUIRED_FIELDS:
            field = extraction.fields.get(dot_path)
            if not field or field.value is None:
                violations.append(ValidationViolation(
                    field_path=dot_path,
                    rule="required",
                    message=f"Required field {dot_path} is missing",
                    severity="error",
                    confidence_penalty=self._REQUIRED_PENALTY,
                ))

        return violations

    # ------------------------------------------------------------------
    # Cross-field consistency
    # ------------------------------------------------------------------
    def _cross_field_checks(self, extraction: ExtractionResult) -> List[ValidationViolation]:
        """Check logical consistency between related fields.

        CUSTOMIZATION POINT: Add your domain-specific cross-field rules here.

        Examples:
        - Total area ≈ sum of component areas (±15% tolerance)
        - If stories=1, no secondary area should exist
        - Conditioned area ≤ total area ≤ area under roof
        """
        violations = []

        # Rule: conditioned area should be ≤ total area
        conditioned = self._get_numeric(extraction, "primaryMetrics.conditionedArea")
        total = self._get_numeric(extraction, "primaryMetrics.totalArea")

        if conditioned is not None and total is not None:
            if conditioned > total * 1.05:  # 5% tolerance for rounding
                violations.append(ValidationViolation(
                    field_path="primaryMetrics.conditionedArea",
                    rule="consistency",
                    message=f"Conditioned area ({conditioned}) > total area ({total})",
                    severity="warning",
                    confidence_penalty=self._CONSISTENCY_PENALTY,
                ))

        # Rule: if stories=1, secondary area should be 0 or None
        stories = self._get_numeric(extraction, "primaryMetrics.stories")
        secondary = self._get_numeric(extraction, "primaryMetrics.secondaryArea")

        if stories is not None and stories == 1 and secondary and secondary > 0:
            violations.append(ValidationViolation(
                field_path="primaryMetrics.secondaryArea",
                rule="consistency",
                message=f"Single-story document has secondary area={secondary}",
                severity="warning",
                confidence_penalty=self._CONSISTENCY_PENALTY,
            ))

        # Rule: total area ≈ conditioned + auxiliary (within 15% tolerance)
        auxiliary = self._get_numeric(extraction, "primaryMetrics.auxiliaryArea")
        if conditioned and auxiliary and total:
            expected = conditioned + auxiliary + (secondary or 0)
            tolerance = total * 0.15
            if abs(total - expected) > tolerance:
                violations.append(ValidationViolation(
                    field_path="primaryMetrics.totalArea",
                    rule="consistency",
                    message=f"Total ({total}) ≠ sum of parts ({expected}) beyond 15% tolerance",
                    severity="warning",
                    confidence_penalty=self._CONSISTENCY_PENALTY,
                ))

        # Add more domain-specific cross-field checks as needed...

        return violations

    # ------------------------------------------------------------------
    # Routing decision
    # ------------------------------------------------------------------
    def _routing_decision(self, extraction: ExtractionResult) -> ReviewDecision:
        """Determine routing based on record confidence and field-level confidence.

        Three tiers:
        - AUTO_ACCEPT: High confidence, no problematic fields
        - AGENT_REVIEW: Medium confidence with specific low-confidence fields to triage
        - HUMAN_REVIEW: Low confidence, too many issues for automated handling
        """
        confidence = extraction.record_confidence
        low_fields = extraction.low_confidence_fields

        if confidence >= self._config.confidence_auto_accept and not low_fields:
            return ReviewDecision.AUTO_ACCEPT

        if confidence >= self._config.confidence_agent_threshold and low_fields:
            return ReviewDecision.AGENT_REVIEW

        if confidence >= self._config.confidence_auto_accept and low_fields:
            # High overall but has specific low-confidence fields → agent review
            return ReviewDecision.AGENT_REVIEW

        return ReviewDecision.HUMAN_REVIEW

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_numeric(extraction: ExtractionResult, dot_path: str) -> Optional[float]:
        """Safely get a numeric value from extraction fields."""
        field = extraction.fields.get(dot_path)
        if not field or field.value is None:
            return None
        try:
            return float(field.value)
        except (TypeError, ValueError):
            return None
