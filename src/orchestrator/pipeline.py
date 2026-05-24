"""Pipeline Orchestrator — end-to-end document extraction with stage sequencing,
error handling, confidence routing, and graceful degradation.

This is the main execution flow:
PDF → Dedup → CU Extraction → AI Gap-Fill → Normalize → Validate → Route → Persist
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from src.config import AppConfig
from src.contracts.extraction_result import (
    ExtractionResult, ExtractionStage, ReviewDecision,
)
from src.extraction.cu_adapter import CUAdapter
from src.agents.ai_schema_mapper import AISchemaMapper
from src.agents.exception_handler import ExceptionHandler
from src.normalization.normalizer import Normalizer
from src.validation.validator import Validator
from src.persistence.cosmos_store import CosmosStore
from src.telemetry.instrumentation import Telemetry

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates the full extraction pipeline with stage-by-stage execution.

    Design principles:
    - Each stage is isolated: failure in one doesn't crash the pipeline
    - Graceful degradation: AI mapper failure → continue with CU-only
    - Agent failure → escalate to human review
    - Full telemetry at every stage transition
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._telemetry = Telemetry(config.app_insights_connection_string)

        # Initialize components
        self._cu_adapter = CUAdapter(
            cu_config=config.cu,
            storage_config=config.storage,
            credential=config.credential,
        )
        self._ai_mapper = AISchemaMapper(
            config=config.foundry,
        ) if config.pipeline.enable_ai_mapper else None

        self._exception_handler = ExceptionHandler(
            config=config.foundry,
        ) if config.pipeline.enable_agent_review else None

        self._normalizer: Optional[Normalizer] = None  # Initialized after schema loads
        self._validator = Validator(config=config.pipeline)
        self._cosmos_store = CosmosStore(config=config.cosmos, credential=config.credential)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, blob_url: str, dry_run: bool = False) -> ExtractionResult:
        """Execute the full extraction pipeline for a single document.

        Args:
            blob_url: Azure Blob Storage URL of the PDF to process.
            dry_run: If True, skip persistence (useful for testing).

        Returns:
            ExtractionResult with final state, routing decision, and all metadata.
        """
        start_time = time.time()
        self._telemetry.track_event("pipeline_start", {"blob_url": blob_url})

        try:
            # ----------------------------------------------------------
            # Stage 1: CU Extraction (primary, deterministic)
            # ----------------------------------------------------------
            extraction = self._stage_extraction(blob_url)
            if extraction.stage == ExtractionStage.FAILED:
                return extraction

            # ----------------------------------------------------------
            # Stage 2: Deduplication check
            # ----------------------------------------------------------
            existing = self._stage_dedup(extraction)
            if existing:
                logger.info("Pipeline: duplicate detected, incrementing version")
                # Could return existing or re-extract — configurable behavior

            # ----------------------------------------------------------
            # Stage 3: AI Gap-Fill (bounded, optional)
            # ----------------------------------------------------------
            extraction = self._stage_ai_mapping(extraction)

            # ----------------------------------------------------------
            # Stage 4: Normalization (deterministic)
            # ----------------------------------------------------------
            normalized_data = self._stage_normalization(extraction)

            # ----------------------------------------------------------
            # Stage 5: Validation + Routing Decision
            # ----------------------------------------------------------
            extraction, violations = self._stage_validation(extraction)

            # ----------------------------------------------------------
            # Stage 6: Agent Review (if routed there)
            # ----------------------------------------------------------
            if extraction.review_decision == ReviewDecision.AGENT_REVIEW:
                extraction = self._stage_agent_review(extraction)

            # ----------------------------------------------------------
            # Stage 7: Persistence
            # ----------------------------------------------------------
            if not dry_run:
                self._stage_persistence(extraction, normalized_data)

            # ----------------------------------------------------------
            # Complete
            # ----------------------------------------------------------
            extraction.stage = ExtractionStage.COMPLETED
            elapsed_ms = int((time.time() - start_time) * 1000)

            self._telemetry.track_event("pipeline_complete", {
                "run_id": extraction.run_id,
                "decision": extraction.review_decision.value if extraction.review_decision else "unknown",
                "fill_rate": f"{extraction.fill_rate:.2f}",
                "record_confidence": f"{extraction.record_confidence:.2f}",
                "elapsed_ms": str(elapsed_ms),
            })

            logger.info(
                "Pipeline: completed run %s — decision=%s, fill_rate=%.1f%%, confidence=%.2f, elapsed=%dms",
                extraction.run_id,
                extraction.review_decision.value if extraction.review_decision else "N/A",
                extraction.fill_rate * 100,
                extraction.record_confidence,
                elapsed_ms,
            )

            return extraction

        except Exception as e:
            logger.exception("Pipeline: unhandled error")
            self._telemetry.track_exception(e)
            raise

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _stage_extraction(self, blob_url: str) -> ExtractionResult:
        """Stage 1: Submit to CU and extract structured fields."""
        self._telemetry.track_event("extraction_start", {"blob_url": blob_url})

        extraction = self._cu_adapter.extract(blob_url)

        self._telemetry.track_event("extraction_complete", {
            "run_id": extraction.run_id,
            "field_count": str(len(extraction.fields)),
            "fill_rate": f"{extraction.fill_rate:.2f}",
        })

        return extraction

    def _stage_dedup(self, extraction: ExtractionResult) -> Optional[dict]:
        """Stage 2: Check if this document has been processed before."""
        return self._cosmos_store.find_by_source_hash(extraction.source_hash)

    def _stage_ai_mapping(self, extraction: ExtractionResult) -> ExtractionResult:
        """Stage 3: AI gap-fill for missing/low-confidence fields."""
        if not self._ai_mapper:
            return extraction

        extraction.stage = ExtractionStage.AI_MAPPING
        self._telemetry.track_event("ai_mapper_start", {"run_id": extraction.run_id})

        try:
            raw_text = self._ai_mapper._raw_response_to_text(extraction.raw_cu_response)
            extraction = self._ai_mapper.fill_gaps(extraction, raw_text)

            self._telemetry.track_event("ai_mapper_done", {
                "run_id": extraction.run_id,
                "fill_rate_after": f"{extraction.fill_rate:.2f}",
            })

        except Exception as e:
            # Graceful degradation: AI failure doesn't stop the pipeline
            logger.warning("Pipeline: AI mapper failed — continuing with CU-only results: %s", e)
            self._telemetry.track_event("ai_mapper_failed", {
                "run_id": extraction.run_id,
                "error": str(e),
            })

        return extraction

    def _stage_normalization(self, extraction: ExtractionResult) -> dict:
        """Stage 4: Normalize all values to canonical types and forms."""
        extraction.stage = ExtractionStage.NORMALIZING

        # Lazy-init normalizer with schema fields from AI mapper
        if not self._normalizer and self._ai_mapper:
            self._normalizer = Normalizer(self._ai_mapper._extractable_fields)

        if self._normalizer:
            return self._normalizer.normalize(extraction)
        return {}

    def _stage_validation(self, extraction: ExtractionResult):
        """Stage 5: Validate and determine routing decision."""
        extraction.stage = ExtractionStage.VALIDATING
        self._telemetry.track_event("validation_start", {"run_id": extraction.run_id})

        return self._validator.validate(extraction)

    def _stage_agent_review(self, extraction: ExtractionResult) -> ExtractionResult:
        """Stage 6: Bounded agent triage for low-confidence fields."""
        if not self._exception_handler:
            # No agent configured — escalate to human
            extraction.review_decision = ReviewDecision.HUMAN_REVIEW
            return extraction

        extraction.stage = ExtractionStage.AGENT_REVIEW
        self._telemetry.track_event("agent_review_start", {
            "run_id": extraction.run_id,
            "low_confidence_count": str(len(extraction.low_confidence_fields)),
        })

        try:
            raw_text = ""
            if self._ai_mapper:
                raw_text = self._ai_mapper._raw_response_to_text(extraction.raw_cu_response)

            patches = self._exception_handler.triage(
                low_confidence_fields=extraction.low_confidence_fields,
                raw_text=raw_text,
            )

            if not patches:
                # Agent returned no patches — escalate to human
                extraction.review_decision = ReviewDecision.HUMAN_REVIEW
                return extraction

            extraction, should_escalate = ExceptionHandler.apply_patches(extraction, patches)

            if should_escalate:
                extraction.review_decision = ReviewDecision.HUMAN_REVIEW
            else:
                extraction.review_decision = ReviewDecision.AUTO_ACCEPT

        except Exception as e:
            # Agent failure → human review
            logger.warning("Pipeline: agent review failed — escalating: %s", e)
            extraction.review_decision = ReviewDecision.HUMAN_REVIEW
            self._telemetry.track_event("agent_review_failed", {
                "run_id": extraction.run_id,
                "error": str(e),
            })

        return extraction

    def _stage_persistence(self, extraction: ExtractionResult, normalized_data: dict) -> None:
        """Stage 7: Persist to Cosmos DB with dedup and versioning."""
        extraction.stage = ExtractionStage.PERSISTING

        if extraction.review_decision == ReviewDecision.HUMAN_REVIEW:
            # Route to human review queue instead of persisting
            self._telemetry.track_event("human_review_required", {
                "run_id": extraction.run_id,
                "confidence": f"{extraction.record_confidence:.2f}",
            })
            return

        doc_id = self._cosmos_store.upsert(extraction, normalized_data)

        self._telemetry.track_event("persisted", {
            "run_id": extraction.run_id,
            "document_id": doc_id,
            "fill_rate": f"{extraction.fill_rate:.2f}",
        })
