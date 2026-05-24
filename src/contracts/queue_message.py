"""Queue Message contract — Service Bus message payload for event-driven processing.

Represents the message structure passed between pipeline stages via Azure Service Bus.
Used for both document-processing triggers and human-review escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from src.contracts.extraction_result import ExtractionStage


@dataclass
class QueueMessage:
    """Message payload for Service Bus queue communication.

    Sent when:
    - A new document is uploaded (document-processing queue)
    - A document is escalated to human review (human-review queue)
    """
    blob_url: str                                    # Source document URL
    run_id: Optional[str] = None                     # Pipeline run ID (set after extraction starts)
    source_hash: Optional[str] = None                # SHA-256 dedup hash
    stage: ExtractionStage = ExtractionStage.INGESTED
    metadata: Dict[str, str] = field(default_factory=dict)  # Custom metadata (region, division, etc.)
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict:
        return {
            "blob_url": self.blob_url,
            "run_id": self.run_id,
            "source_hash": self.source_hash,
            "stage": self.stage.value,
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QueueMessage:
        return cls(
            blob_url=data["blob_url"],
            run_id=data.get("run_id"),
            source_hash=data.get("source_hash"),
            stage=ExtractionStage(data.get("stage", "ingested")),
            metadata=data.get("metadata", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )
