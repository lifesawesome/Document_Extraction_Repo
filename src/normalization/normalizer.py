"""Normalizer — deterministic type coercion and canonical form transformation.

Runs AFTER AI gap-fill, BEFORE validation. Ensures all field values conform
to their schema-defined types and formats. This is a deterministic stage —
no AI, no network calls, fully testable offline.

CUSTOMIZATION POINT: Add domain-specific normalization transforms in _apply_transforms().
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.contracts.extraction_result import ExtractionResult, FieldResult

logger = logging.getLogger(__name__)


class Normalizer:
    """Deterministic normalization: type coercion, formatting, and defaults."""

    def __init__(self, schema_fields: Dict[str, dict]):
        """
        Args:
            schema_fields: Extractable field definitions from target_schema.json.
                          Key = dot-path, Value = {"type": "...", "description": "..."}
        """
        self._schema_fields = schema_fields

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def normalize(self, extraction: ExtractionResult) -> Dict[str, Any]:
        """Normalize all filled fields to their target types and return a flat dict.

        Returns a dict of {dot_path: normalized_value} suitable for persistence.
        """
        normalized: Dict[str, Any] = {}

        for dot_path, field_result in extraction.fields.items():
            if field_result.value is None:
                normalized[dot_path] = None
                continue

            schema_meta = self._schema_fields.get(dot_path, {})
            target_type = schema_meta.get("type", "string")

            # Type coercion
            coerced = self._coerce_type(field_result.value, target_type)

            # Domain-specific transforms
            transformed = self._apply_transforms(dot_path, coerced)

            normalized[dot_path] = transformed

        return normalized

    # ------------------------------------------------------------------
    # Type coercion
    # ------------------------------------------------------------------
    def _coerce_type(self, value: Any, target_type: str) -> Any:
        """Coerce a value to the schema-defined type."""
        try:
            if target_type == "integer":
                return self._to_int(value)
            elif target_type == "number":
                return self._to_float(value)
            elif target_type == "boolean":
                return self._to_bool(value)
            elif target_type == "string":
                return self._to_string(value)
            elif target_type == "string_list":
                return self._to_string_list(value)
            else:
                return value
        except (ValueError, TypeError):
            logger.warning("Normalizer: failed to coerce %r to %s", value, target_type)
            return value

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        # Extract digits from string (e.g., "2,523 sq ft" → 2523)
        text = str(value).replace(",", "").strip()
        match = re.search(r"-?\d+", text)
        return int(match.group()) if match else None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace(",", "").strip()
        match = re.search(r"-?\d+\.?\d*", text)
        return float(match.group()) if match else None

    @staticmethod
    def _to_bool(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "y", "1"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
        return None

    @staticmethod
    def _to_string(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip()

    @staticmethod
    def _to_string_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if v]
        # Parse comma-separated string
        text = str(value)
        return [item.strip() for item in text.split(",") if item.strip()]

    # ------------------------------------------------------------------
    # Domain-specific transforms
    # ------------------------------------------------------------------
    def _apply_transforms(self, dot_path: str, value: Any) -> Any:
        """Apply domain-specific transformations based on field path.

        CUSTOMIZATION POINT: Add your domain-specific normalization here.

        Examples:
        - Title-case names: "JOHN SMITH" → "John Smith"
        - Strip suffixes: "ACME ARCHITECTS INC" → "Acme"
        - Parse dates: "01/15/24" → 2024
        - Normalize enums: "brick veneer" → "Brick Veneer"
        """
        # Example: firm name normalization (strip common suffixes, title case)
        if dot_path.endswith("firmName") and isinstance(value, str):
            return self._normalize_firm_name(value)

        # Example: year extraction from date strings
        if dot_path.endswith("yearOfCreation") and isinstance(value, (str, int)):
            return self._normalize_year(value)

        # Example: title case for names/titles
        if dot_path.endswith(("documentTitle", "authorName")) and isinstance(value, str):
            return value.title() if value.isupper() else value

        return value

    @staticmethod
    def _normalize_firm_name(name: str) -> str:
        """Strip common business suffixes and title-case."""
        suffixes = ["ARCHITECTS", "ARCHITECTURE", "ENGINEERING", "INC", "LLC", "CORP",
                    "LTD", "CO", "GROUP", "ASSOCIATES", "& ASSOCIATES"]
        result = name.strip()
        for suffix in suffixes:
            result = re.sub(rf"\b{suffix}\b\.?", "", result, flags=re.IGNORECASE)
        result = result.strip().rstrip(",").strip()
        return result.title() if result.isupper() else result

    @staticmethod
    def _normalize_year(value: Any) -> Optional[int]:
        """Extract 4-digit year from various date formats."""
        text = str(value).strip()

        # Already a 4-digit year
        if re.match(r"^\d{4}$", text):
            return int(text)

        # 2-digit year
        if re.match(r"^\d{2}$", text):
            year = int(text)
            return 2000 + year if year < 50 else 1900 + year

        # Extract year from date formats (MM/DD/YYYY, YYYY-MM-DD, etc.)
        match = re.search(r"(19|20)\d{2}", text)
        if match:
            return int(match.group())

        # Try 2-digit year in date format (MM/DD/YY)
        match = re.search(r"/(\d{2})$", text)
        if match:
            year = int(match.group(1))
            return 2000 + year if year < 50 else 1900 + year

        return None
