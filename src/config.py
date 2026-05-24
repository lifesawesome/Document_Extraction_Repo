"""Configuration module — loads environment variables and provides typed config objects.

Supports DefaultAzureCredential (Managed Identity in production, az login locally).
No API keys are committed to code — all secrets come from environment or Key Vault.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()  # Load .env file for local development


@dataclass
class CUConfig:
    """Azure Content Understanding configuration."""
    endpoint: str = field(default_factory=lambda: os.environ["CU_ENDPOINT"])
    analyzer_name: str = field(default_factory=lambda: os.getenv("CU_ANALYZER_NAME", "document-analyzer"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("CU_KEY"))
    api_version: str = "2024-12-01-preview"
    poll_interval_seconds: int = 10
    max_poll_minutes: int = 20


@dataclass
class FoundryConfig:
    """Azure AI Foundry / OpenAI configuration."""
    openai_endpoint: str = field(default_factory=lambda: os.environ["FOUNDRY_OPENAI_ENDPOINT"])
    model: str = field(default_factory=lambda: os.getenv("FOUNDRY_MODEL", "gpt-4.1"))
    tenant_id: Optional[str] = field(default_factory=lambda: os.getenv("FOUNDRY_TENANT_ID"))
    api_version: str = "2024-12-01-preview"


@dataclass
class CosmosConfig:
    """Azure Cosmos DB configuration."""
    endpoint: str = field(default_factory=lambda: os.environ["COSMOS_ENDPOINT"])
    database_name: str = field(default_factory=lambda: os.getenv("COSMOS_DATABASE", "documents"))
    container_name: str = field(default_factory=lambda: os.getenv("COSMOS_CONTAINER", "extractions"))
    key: Optional[str] = field(default_factory=lambda: os.getenv("COSMOS_KEY"))


@dataclass
class StorageConfig:
    """Azure Blob Storage configuration."""
    connection_string: Optional[str] = field(default_factory=lambda: os.getenv("STORAGE_CONNECTION_STRING"))
    account_url: Optional[str] = field(default_factory=lambda: os.getenv("STORAGE_ACCOUNT_URL"))
    staging_container: str = "pdf-staging"
    results_container: str = "extraction-results"


@dataclass
class PipelineConfig:
    """Pipeline behavior configuration — confidence thresholds and feature flags."""
    confidence_auto_accept: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_AUTO_ACCEPT", "0.85"))
    )
    confidence_agent_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_AGENT_THRESHOLD", "0.60"))
    )
    low_confidence_field_threshold: float = field(
        default_factory=lambda: float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.70"))
    )
    enable_ai_mapper: bool = field(
        default_factory=lambda: os.getenv("ENABLE_AI_MAPPER", "true").lower() == "true"
    )
    enable_agent_review: bool = field(
        default_factory=lambda: os.getenv("ENABLE_AGENT_REVIEW", "true").lower() == "true"
    )
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))


@dataclass
class AppConfig:
    """Top-level application configuration aggregating all service configs."""
    cu: CUConfig = field(default_factory=CUConfig)
    foundry: FoundryConfig = field(default_factory=FoundryConfig)
    cosmos: CosmosConfig = field(default_factory=CosmosConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    credential: DefaultAzureCredential = field(default_factory=DefaultAzureCredential)

    # Application Insights connection string (optional — telemetry disabled if absent)
    app_insights_connection_string: Optional[str] = field(
        default_factory=lambda: os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    )
