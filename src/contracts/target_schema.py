"""Target Schema contract — typed representation of the final extracted document.

This module provides a Python dataclass that mirrors the target_schema.json structure.
Use it for type-safe access to normalized extraction results before persistence.

CUSTOMIZATION POINT: Update this class to match your target_schema.json sections.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DocumentInfo:
    """Core document identification fields."""
    document_number: Optional[str] = None
    document_variant: Optional[str] = None
    document_title: Optional[str] = None
    issue_date: Optional[str] = None
    year_of_creation: Optional[int] = None
    firm_name: Optional[str] = None
    author_name: Optional[str] = None


@dataclass
class PrimaryMetrics:
    """Primary quantitative measurements."""
    total_area: Optional[float] = None
    conditioned_area: Optional[float] = None
    secondary_area: Optional[float] = None
    auxiliary_area: Optional[float] = None
    stories: Optional[int] = None


@dataclass
class Features:
    """Boolean feature flags."""
    has_feature_a: Optional[bool] = None
    has_feature_b: Optional[bool] = None


@dataclass
class StructuralDetails:
    """Structural and component details."""
    primary_rooms: Optional[int] = None
    secondary_rooms: Optional[int] = None
    features: Features = field(default_factory=Features)
    materials: List[str] = field(default_factory=list)
    structural_type: Optional[str] = None


@dataclass
class TargetSchema:
    """Complete target document structure — mirrors target_schema.json.

    CUSTOMIZATION POINT: Add/remove sections to match your domain schema.
    """
    document_info: DocumentInfo = field(default_factory=DocumentInfo)
    primary_metrics: PrimaryMetrics = field(default_factory=PrimaryMetrics)
    structural_details: StructuralDetails = field(default_factory=StructuralDetails)

    # System-managed fields (set by pipeline, not extracted)
    division: Optional[str] = None
    region: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    version_id: int = 1

    def to_dict(self) -> dict:
        """Serialize to flat dot-path dict for Cosmos persistence."""
        result: Dict[str, Any] = {}
        # Document info
        for k, v in vars(self.document_info).items():
            if v is not None:
                result[f"documentInfo.{self._to_camel(k)}"] = v
        # Primary metrics
        for k, v in vars(self.primary_metrics).items():
            if v is not None:
                result[f"primaryMetrics.{self._to_camel(k)}"] = v
        # Structural details
        for k, v in vars(self.structural_details).items():
            if k == "features":
                for fk, fv in vars(v).items():
                    if fv is not None:
                        result[f"structuralDetails.features.{self._to_camel(fk)}"] = fv
            elif v is not None and v != []:
                result[f"structuralDetails.{self._to_camel(k)}"] = v
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TargetSchema:
        """Reconstruct from flat dot-path dict."""
        schema = cls()
        for dot_path, value in data.items():
            parts = dot_path.split(".")
            if len(parts) >= 2:
                section = parts[0]
                field_name = cls._to_snake(parts[-1])
                if section == "documentInfo":
                    setattr(schema.document_info, field_name, value)
                elif section == "primaryMetrics":
                    setattr(schema.primary_metrics, field_name, value)
                elif section == "structuralDetails":
                    if len(parts) == 3 and parts[1] == "features":
                        setattr(schema.structural_details.features, field_name, value)
                    else:
                        setattr(schema.structural_details, field_name, value)
        return schema

    @staticmethod
    def _to_camel(snake: str) -> str:
        parts = snake.split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])

    @staticmethod
    def _to_snake(camel: str) -> str:
        import re
        return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()
