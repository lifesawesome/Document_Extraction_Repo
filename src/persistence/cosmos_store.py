"""Cosmos DB Store — persistence with deduplication, versioning, and audit trail.

Handles:
- Source hash–based deduplication (same document → version increment)
- Upsert with automatic versioning and timestamps
- Query by source hash for dedup checks
- Serverless-friendly (minimal RU consumption)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

from src.config import CosmosConfig
from src.contracts.extraction_result import ExtractionResult

logger = logging.getLogger(__name__)


class CosmosStore:
    """Cosmos DB persistence layer with deduplication and versioning."""

    def __init__(self, config: CosmosConfig, credential: Optional[DefaultAzureCredential] = None):
        self._config = config

        # Authenticate via Managed Identity (preferred) or key fallback
        if config.key:
            self._client = CosmosClient(config.endpoint, credential=config.key)
        else:
            self._client = CosmosClient(
                config.endpoint,
                credential=credential or DefaultAzureCredential(),
            )

        self._database = self._client.get_database_client(config.database_name)
        self._container = self._database.get_container_client(config.container_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def find_by_source_hash(self, source_hash: str) -> Optional[dict]:
        """Check if a document with this source hash already exists (dedup).

        Returns the existing document dict if found, None otherwise.
        """
        query = "SELECT * FROM c WHERE c.source_hash = @hash"
        params = [{"name": "@hash", "value": source_hash}]

        items = list(self._container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
            max_item_count=1,
        ))

        return items[0] if items else None

    def upsert(
        self,
        extraction: ExtractionResult,
        normalized_data: Dict[str, Any],
    ) -> str:
        """Persist extraction result to Cosmos DB with versioning.

        If a document with the same source_hash exists → increment version.
        Otherwise → create new document.

        Returns the Cosmos document ID.
        """
        existing = self.find_by_source_hash(extraction.source_hash)
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            # Version increment — update existing document
            doc_id = existing["id"]
            version = existing.get("version_id", 1) + 1
            document = self._build_document(
                extraction, normalized_data, doc_id, version,
                created_at=existing.get("created_at", now),
                updated_at=now,
            )
        else:
            # New document
            doc_id = str(uuid.uuid4())
            version = 1
            document = self._build_document(
                extraction, normalized_data, doc_id, version,
                created_at=now,
                updated_at=now,
            )

        self._container.upsert_item(document)

        logger.info(
            "CosmosStore: upserted document %s (version %d, fill_rate %.1f%%)",
            doc_id, version, extraction.fill_rate * 100,
        )

        return doc_id

    # ------------------------------------------------------------------
    # Document construction
    # ------------------------------------------------------------------
    def _build_document(
        self,
        extraction: ExtractionResult,
        normalized_data: Dict[str, Any],
        doc_id: str,
        version: int,
        created_at: str,
        updated_at: str,
    ) -> dict:
        """Build the Cosmos document combining normalized data + metadata."""
        # Partition key — customize based on your partitioning strategy
        # Common choices: document type, region, customer ID
        partition_key = self._extract_partition_key(normalized_data)

        document = {
            "id": doc_id,
            "partition_key": partition_key,
            "source_hash": extraction.source_hash,
            "source_url": extraction.source_url,
            "version_id": version,
            "created_at": created_at,
            "updated_at": updated_at,
            "created_by": extraction.run_id,

            # Pipeline metadata
            "fill_rate": extraction.fill_rate,
            "record_confidence": extraction.record_confidence,
            "review_decision": extraction.review_decision.value if extraction.review_decision else None,

            # Extracted & normalized data (flattened into document)
            **self._nest_normalized_data(normalized_data),
        }

        return document

    @staticmethod
    def _extract_partition_key(normalized_data: Dict[str, Any]) -> str:
        """Determine partition key from normalized data.

        CUSTOMIZATION POINT: Choose your partitioning strategy.
        Options: document_type, region, customer_id, date-based, etc.
        """
        # Default: use document number as partition key
        return str(normalized_data.get("documentInfo.documentNumber", "unknown"))

    @staticmethod
    def _nest_normalized_data(flat_data: Dict[str, Any]) -> dict:
        """Convert flat dot-path data to nested document structure.

        "primaryMetrics.totalArea" → {"primaryMetrics": {"totalArea": value}}
        """
        nested: dict = {}
        for dot_path, value in flat_data.items():
            if value is None:
                continue
            parts = dot_path.split(".")
            current = nested
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value
        return nested
