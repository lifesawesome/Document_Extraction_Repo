"""AI Schema Mapper — fills extraction gaps using GPT + runtime schema definition.

Positioned between CU extraction and normalization. The mapper:
1. Loads the target schema once on init to learn every extractable field.
2. After the CU adapter runs, compares the extraction result against the full
   field inventory to find missing or low-confidence fields.
3. Sends those gaps plus the raw document text to GPT, asking it to locate values.
4. Merges any newly extracted values back into the ExtractionResult.

This keeps the deterministic CU adapter as the primary path and only invokes
the LLM for leftovers — bounded cost, bounded latency.

CUSTOMIZATION POINT: Update _SYSTEM_PROMPT with your domain-specific extraction rules.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

from src.config import FoundryConfig
from src.contracts.extraction_result import ExtractionResult, FieldResult

logger = logging.getLogger(__name__)

_DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "target_schema.json"

# =============================================================================
# CUSTOMIZATION POINT: Domain-Specific System Prompt
# =============================================================================
# Replace the DOMAIN RULES section below with rules specific to YOUR document type.
# Examples:
# - Insurance: "The CLAIM NUMBER is always in the header, format XXX-XXXXXXX"
# - Legal: "EFFECTIVE DATE is in the first paragraph of Section 1"
# - Construction: "TOTAL AREA uses the FRAME column, not WITH MASONRY"

_SYSTEM_PROMPT = """\
You are a precise data extraction and VERIFICATION assistant for structured documents.

You receive:
1. A list of fields with their current extracted values (from a prior OCR/AI pass).
2. Raw markdown/OCR text from the source document.

Your job: for EACH field, verify or correct the current value using the raw text.

GENERAL RULES:
- If a value is genuinely not present in the document, set it to null.
- If the current value appears WRONG based on the document text, CORRECT it.
- If the current value looks correct, KEEP it — return the same value.
- Coerce to the correct type: integer → int, number → float, boolean → true/false,
  string → string, string_list → ["a","b"].

CRITICAL — Multi-Section Documents:
- Complex documents often contain MULTIPLE sections with similar-looking data.
- Always prefer data from the PRIMARY section (usually the first occurrence).
- Do NOT confuse values from supplementary/appendix sections with the main content.

CRITICAL — Tables with Multiple Columns:
- When a table has multiple measurement columns, use the column specified by the field description.
- Example: if a table has "Gross" and "Net" columns, use the correct one per field requirements.
- Use values from the FIRST matching table you encounter (closest to the primary content).

# =========================================================================
# DOMAIN RULES (customize below for your specific document type)
# =========================================================================
# Add your domain-specific extraction rules here. Examples:
#
# - For insurance claims:
#   "Claim Number format is XXX-XXXXXXX, found in the document header"
#   "Loss Date is in Section 1, not the filing date in the footer"
#
# - For legal contracts:
#   "Effective Date is the date the agreement starts, not the signing date"
#   "Party names should exclude legal suffixes (LLC, Inc, Corp)"
#
# - For architectural plans:
#   "Use FRAME column for conditioned area, WITH MASONRY for total area"
#   "Room labels on floor plans are authoritative (FAMILY ROOM vs GREAT ROOM)"
# =========================================================================

OUTPUT FORMAT:
- Return ONLY a JSON object mapping field dot-paths to extracted values.
- Use the exact field paths provided in the input.
- No markdown fences, no explanation — pure JSON only.
"""


class AISchemaMapper:
    """Uses GPT to fill extraction gaps identified by comparing the CU result
    against the full extractable-field inventory.

    Design principles:
    - CU is primary; GPT is secondary verification only
    - Only processes missing or low-confidence fields (bounded cost)
    - Preserves high-confidence CU values (never overwrites good data)
    - Graceful degradation (if GPT fails, pipeline continues with CU-only)
    """

    # Fields below this confidence threshold are sent to GPT for verification
    _LOW_CONFIDENCE_THRESHOLD = 0.70

    # AI-filled fields get this confidence score (lower than high-confidence CU)
    _AI_FILL_CONFIDENCE = 0.65

    def __init__(
        self,
        config: FoundryConfig,
        schema_path: Optional[str] = None,
    ):
        self._config = config
        self._credential = DefaultAzureCredential()
        self._openai = AzureOpenAI(
            azure_endpoint=config.openai_endpoint,
            azure_ad_token_provider=self._get_token,
            api_version=config.api_version,
        )
        self._extractable_fields = self._load_extractable_fields(
            schema_path or str(_DEFAULT_SCHEMA_PATH)
        )

    def _get_token(self) -> str:
        return self._credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fill_gaps(
        self,
        extraction: ExtractionResult,
        raw_text: Optional[str] = None,
    ) -> ExtractionResult:
        """Identify missing/low-confidence fields and attempt to fill them via GPT.

        Args:
            extraction: Current extraction result from CU adapter.
            raw_text: Plain-text/markdown content from the document.
                      Falls back to raw CU response if not provided.

        Returns:
            The same ExtractionResult instance with gap fields merged in.
        """
        gap_fields = self._identify_gaps(extraction)

        if not gap_fields:
            logger.info("AISchemaMapper: no gaps to fill for run %s", extraction.run_id)
            return extraction

        logger.info(
            "AISchemaMapper: %d gap fields identified for run %s",
            len(gap_fields), extraction.run_id,
        )

        text = raw_text or self._raw_response_to_text(extraction.raw_cu_response)
        if not text:
            logger.warning("AISchemaMapper: no raw text available — skipping gap fill")
            return extraction

        extracted = self._call_model(gap_fields, text, extraction)

        merged = 0
        skipped_cu = 0
        for dot_path, value in extracted.items():
            if value is None:
                continue

            existing = extraction.fields.get(dot_path)

            # CRITICAL: Preserve high-confidence CU values — never let GPT overwrite them
            if (existing and existing.value is not None
                    and existing.confidence is not None
                    and existing.confidence >= self._LOW_CONFIDENCE_THRESHOLD):
                skipped_cu += 1
                continue

            was_missing = not existing or existing.value is None
            extraction.fields[dot_path] = FieldResult(
                field_path=dot_path,
                value=value,
                confidence=self._AI_FILL_CONFIDENCE,
                source="ai_mapper",
                status="filled",
                note="Filled by AI schema mapper" if was_missing
                     else "Corrected by AI schema mapper",
            )
            merged += 1

        logger.info(
            "AISchemaMapper: merged %d fields, preserved %d high-confidence CU fields for run %s",
            merged, skipped_cu, extraction.run_id,
        )
        return extraction

    # ------------------------------------------------------------------
    # Schema loading
    # ------------------------------------------------------------------
    @staticmethod
    def _load_extractable_fields(schema_path: str) -> Dict[str, dict]:
        """Parse target_schema.json and return extractable fields.

        Key   = dot-path  (e.g., "primaryMetrics.totalArea")
        Value = field metadata (type, description, required, ...)
        """
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)

        fields: Dict[str, dict] = {}
        sections = schema.get("sections", {})

        for section_name, section_body in sections.items():
            if not isinstance(section_body, dict):
                continue

            # Skip non-extractable sections (system, metadata)
            category = section_body.get("$category", "")
            if category in ("system", "cosmos_metadata"):
                continue

            for field_name, field_meta in section_body.items():
                if field_name.startswith("$"):
                    continue

                if isinstance(field_meta, dict) and field_meta.get("$type") == "object":
                    # Nested object — iterate sub-fields
                    for sub_name, sub_meta in field_meta.items():
                        if sub_name.startswith("$"):
                            continue
                        if isinstance(sub_meta, dict) and sub_meta.get("extractable", False):
                            dot_path = f"{section_name}.{field_name}.{sub_name}"
                            fields[dot_path] = sub_meta

                elif isinstance(field_meta, dict) and field_meta.get("extractable", False):
                    dot_path = f"{section_name}.{field_name}"
                    fields[dot_path] = field_meta

        logger.info("AISchemaMapper: loaded %d extractable fields from schema", len(fields))
        return fields

    # ------------------------------------------------------------------
    # Gap identification
    # ------------------------------------------------------------------
    def _identify_gaps(self, extraction: ExtractionResult) -> Dict[str, dict]:
        """Return fields that are missing or have low CU confidence."""
        gaps: Dict[str, dict] = {}
        for dot_path, meta in self._extractable_fields.items():
            field = extraction.fields.get(dot_path)
            if field is None or field.value is None or field.status == "not_filled":
                gaps[dot_path] = meta  # Truly missing — needs GPT
            elif (field.confidence is not None
                  and field.confidence < self._LOW_CONFIDENCE_THRESHOLD):
                gaps[dot_path] = meta  # Low confidence — GPT should verify
        return gaps

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------
    def _call_model(
        self,
        gap_fields: Dict[str, dict],
        raw_text: str,
        extraction: Optional[ExtractionResult] = None,
    ) -> Dict[str, Any]:
        """Send gap fields + raw text to GPT and parse JSON response."""
        field_descriptions = []
        for dot_path, meta in gap_fields.items():
            entry: dict = {
                "field": dot_path,
                "type": meta.get("type", "string"),
                "description": meta.get("description", ""),
            }
            # Include current CU value so GPT can verify/correct
            if extraction:
                fr = extraction.fields.get(dot_path)
                if fr and fr.value is not None:
                    entry["current_value"] = fr.value
                    entry["current_source"] = fr.source or "cu"
            field_descriptions.append(entry)

        user_payload = {
            "fields_to_verify_and_extract": field_descriptions,
            # Truncate to prevent cost explosion — 60K chars ≈ 15K tokens
            "raw_document_text": raw_text[:60_000],
        }
        user_message = json.dumps(user_payload, indent=2, default=str)

        try:
            response = self._openai.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,  # Deterministic output
                response_format={"type": "json_object"},  # Enforce JSON
            )
            assistant_text = response.choices[0].message.content or ""
            return self._parse_response(assistant_text)

        except Exception:
            logger.exception("AISchemaMapper: model call failed — continuing without AI fill")
            return {}

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(text: str) -> Dict[str, Any]:
        """Parse GPT's JSON response into a field→value dict."""
        text = text.strip()
        # Handle markdown-wrapped JSON (shouldn't happen with response_format, but defensive)
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AISchemaMapper: non-JSON response from model")
            return {}

        if not isinstance(result, dict):
            logger.warning("AISchemaMapper: expected JSON object, got %s", type(result).__name__)
            return {}
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _raw_response_to_text(raw_cu_response: Optional[dict]) -> str:
        """Extract readable text from CU response for GPT context."""
        if not raw_cu_response:
            return ""
        # Content Understanding format: contents[0].markdown
        contents = raw_cu_response.get("contents", [])
        if contents and isinstance(contents[0], dict):
            md = contents[0].get("markdown", "")
            if md:
                return md
        # Legacy Document Intelligence format: analyzeResult.content
        analyze_result = raw_cu_response.get("analyzeResult", {})
        content = analyze_result.get("content", "")
        if content:
            return content
        # Fallback: JSON dump (truncated)
        return json.dumps(raw_cu_response, default=str)[:60_000]
