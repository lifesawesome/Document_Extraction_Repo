"""Exception Handler — bounded AI agent for triaging low-confidence fields.

This agent is invoked ONLY when:
- Record confidence is between 0.60 and 0.84 (agent_review zone)
- There are specific low-confidence fields that need triage

The agent receives ONLY the low-confidence fields + raw document text (bounded scope).
It returns structured patches: CORRECT (new value), ACCEPT (keep existing), or ESCALATE (human needed).

If the agent fails for any reason → automatic escalation to human review.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

from src.config import FoundryConfig
from src.contracts.extraction_result import ExtractionResult, FieldResult

logger = logging.getLogger(__name__)

_AGENT_SYSTEM_PROMPT = """\
You are a document extraction quality reviewer. You receive fields that have LOW confidence
scores and need your decision.

For EACH field, you must return ONE of these actions:
- CORRECT: The current value is wrong. Provide the correct value.
- ACCEPT: The current value is correct despite low confidence. Keep it.
- ESCALATE: You cannot determine the correct value. Route to human review.

Rules:
- Only CORRECT if you have HIGH confidence the value is wrong based on the document text.
- ACCEPT if the value seems plausible and consistent with surrounding context.
- ESCALATE if the field is ambiguous, the document text is unclear, or you're uncertain.
- When in doubt, ESCALATE. False corrections are worse than human review.

Return a JSON array of patch objects:
[
  {"field": "dot.path", "action": "CORRECT", "value": <new_value>, "reason": "..."},
  {"field": "dot.path", "action": "ACCEPT", "reason": "..."},
  {"field": "dot.path", "action": "ESCALATE", "reason": "..."}
]
"""


class ExceptionHandler:
    """Bounded agent that triages low-confidence fields.

    Design principles:
    - Receives ONLY low-confidence fields (not the full document)
    - Returns structured patches (not free-form text)
    - Failure → automatic escalation to human review
    - No unbounded reasoning or autonomous actions
    """

    def __init__(self, config: FoundryConfig):
        self._config = config
        self._credential = DefaultAzureCredential()
        self._openai = AzureOpenAI(
            azure_endpoint=config.openai_endpoint,
            azure_ad_token_provider=self._get_token,
            api_version=config.api_version,
        )

    def _get_token(self) -> str:
        return self._credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def triage(
        self,
        low_confidence_fields: List[FieldResult],
        raw_text: str,
    ) -> List[Dict[str, Any]]:
        """Triage low-confidence fields and return structured patches.

        Args:
            low_confidence_fields: Fields with confidence < 0.85 that need review.
            raw_text: Raw document text for context.

        Returns:
            List of patch dicts with 'field', 'action', optional 'value', and 'reason'.
            Empty list if agent fails (caller should escalate to human review).
        """
        if not low_confidence_fields:
            return []

        field_data = [
            {
                "field": f.field_path,
                "current_value": f.value,
                "confidence": f.confidence,
                "source": f.source,
            }
            for f in low_confidence_fields
        ]

        user_payload = {
            "low_confidence_fields": field_data,
            "raw_document_text": raw_text[:40_000],  # Bounded input
        }

        try:
            response = self._openai.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": _AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload, default=str)},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or ""
            return self._parse_patches(text)

        except Exception:
            logger.exception("ExceptionHandler: agent call failed — escalating to human review")
            return []  # Empty = caller should escalate

    # ------------------------------------------------------------------
    # Patch parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_patches(text: str) -> List[Dict[str, Any]]:
        """Parse agent response into structured patches."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("ExceptionHandler: non-JSON response — escalating")
            return []

        # Handle both {"patches": [...]} and [...] formats
        if isinstance(result, dict):
            patches = result.get("patches", result.get("results", []))
        elif isinstance(result, list):
            patches = result
        else:
            return []

        # Validate patch structure
        valid_patches = []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            if "field" not in patch or "action" not in patch:
                continue
            if patch["action"] not in ("CORRECT", "ACCEPT", "ESCALATE"):
                continue
            valid_patches.append(patch)

        return valid_patches

    # ------------------------------------------------------------------
    # Patch application (called by pipeline/normalizer)
    # ------------------------------------------------------------------
    @staticmethod
    def apply_patches(
        extraction: ExtractionResult,
        patches: List[Dict[str, Any]],
    ) -> tuple[ExtractionResult, bool]:
        """Apply agent patches to extraction result.

        Returns:
            Tuple of (updated ExtractionResult, should_escalate).
            should_escalate is True if any field was ESCALATE'd.
        """
        should_escalate = False

        for patch in patches:
            field_path = patch["field"]
            action = patch["action"]
            reason = patch.get("reason", "")

            if action == "CORRECT":
                extraction.fields[field_path] = FieldResult(
                    field_path=field_path,
                    value=patch.get("value"),
                    confidence=0.80,  # Agent corrections get moderate confidence
                    source="agent",
                    status="corrected",
                    note=f"Agent corrected: {reason}",
                )

            elif action == "ACCEPT":
                existing = extraction.fields.get(field_path)
                if existing:
                    existing.confidence = max(existing.confidence or 0, 0.80)
                    existing.note = f"Agent accepted: {reason}"

            elif action == "ESCALATE":
                should_escalate = True
                existing = extraction.fields.get(field_path)
                if existing:
                    existing.note = f"Agent escalated: {reason}"

        return extraction, should_escalate
