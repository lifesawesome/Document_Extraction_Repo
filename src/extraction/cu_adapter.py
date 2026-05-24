"""Content Understanding Adapter — integrates with Azure Content Understanding for
deterministic document extraction with per-field confidence scores.

This is the PRIMARY extraction path. The adapter:
1. Submits a document (blob URL or local file) to a CU custom analyzer.
2. Polls until extraction completes (up to 20 minutes).
3. Maps CU output fields to your target schema dot-paths.
4. Returns an ExtractionResult with per-field confidence scores.

CUSTOMIZATION POINT: Update CU_FIELD_MAP to match your CU analyzer's field names
to your target schema paths.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, generate_blob_sas, BlobSasPermissions

from src.config import CUConfig, StorageConfig
from src.contracts.extraction_result import ExtractionResult, ExtractionStage, FieldResult

logger = logging.getLogger(__name__)

# =============================================================================
# CUSTOMIZATION POINT: Map your CU analyzer field names → target schema dot-paths
# =============================================================================
# Key = field name as returned by your Content Understanding analyzer
# Value = dot-path in your target schema (e.g., "primaryMetrics.totalArea")
#
# Update this mapping when you:
# - Change your CU analyzer field definitions
# - Add new fields to your target schema
# - Rename schema sections

CU_FIELD_MAP: Dict[str, str] = {
    # Document identification
    "DocumentNumber": "documentInfo.documentNumber",
    "DocumentVariant": "documentInfo.documentVariant",
    "DocumentTitle": "documentInfo.documentTitle",
    "IssueDate": "documentInfo.issueDate",
    "YearOfCreation": "documentInfo.yearOfCreation",
    "FirmName": "documentInfo.firmName",
    "AuthorName": "documentInfo.authorName",

    # Primary measurements
    "TotalArea": "primaryMetrics.totalArea",
    "ConditionedArea": "primaryMetrics.conditionedArea",
    "SecondaryArea": "primaryMetrics.secondaryArea",
    "AuxiliaryArea": "primaryMetrics.auxiliaryArea",
    "Stories": "primaryMetrics.stories",

    # Structural details
    "PrimaryRooms": "structuralDetails.primaryRooms",
    "SecondaryRooms": "structuralDetails.secondaryRooms",
    "HasFeatureA": "structuralDetails.features.hasFeatureA",
    "HasFeatureB": "structuralDetails.features.hasFeatureB",
    "Materials": "structuralDetails.materials",
    "StructuralType": "structuralDetails.structuralType",

    # Add your domain-specific field mappings here...
}


class CUAdapter:
    """Submits documents to Azure Content Understanding and maps extracted fields
    to the target schema with per-field confidence tracking.
    """

    def __init__(
        self,
        cu_config: CUConfig,
        storage_config: Optional[StorageConfig] = None,
        credential: Optional[DefaultAzureCredential] = None,
    ):
        self._config = cu_config
        self._storage_config = storage_config
        self._credential = credential or DefaultAzureCredential()
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def extract(self, blob_url: str) -> ExtractionResult:
        """Run full extraction: submit → poll → map fields.

        Args:
            blob_url: Azure Blob Storage URL of the document to extract.

        Returns:
            ExtractionResult with per-field confidence scores and raw CU response.
        """
        source_hash = hashlib.sha256(blob_url.encode()).hexdigest()
        run_id = f"{source_hash[:8]}-{int(time.time())}"

        result = ExtractionResult(
            run_id=run_id,
            source_url=blob_url,
            source_hash=source_hash,
            stage=ExtractionStage.EXTRACTING,
        )

        try:
            # Step 1: Submit document for analysis
            operation_url = self._submit_analysis(blob_url)

            # Step 2: Poll until complete
            raw_response = self._poll_result(operation_url)
            result.raw_cu_response = raw_response

            # Step 3: Map CU fields to schema paths
            self._map_fields(raw_response, result)

            logger.info(
                "CUAdapter: extracted %d fields (fill rate %.1f%%) for run %s",
                len(result.fields), result.fill_rate * 100, run_id,
            )

        except Exception as e:
            logger.exception("CUAdapter: extraction failed for %s", blob_url)
            result.stage = ExtractionStage.FAILED
            result.errors.append(f"CU extraction failed: {str(e)}")

        return result

    # ------------------------------------------------------------------
    # CU API interaction
    # ------------------------------------------------------------------
    def _submit_analysis(self, blob_url: str) -> str:
        """Submit document to CU analyzer and return the operation URL for polling."""
        # Generate SAS URL if needed (CU requires accessible URL)
        accessible_url = self._ensure_accessible_url(blob_url)

        url = (
            f"{self._config.endpoint}/contentunderstanding/analyzers/"
            f"{self._config.analyzer_name}:analyze"
            f"?api-version={self._config.api_version}"
        )

        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"

        payload = {"url": accessible_url}

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        # CU returns 202 Accepted with Operation-Location header
        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise RuntimeError("CU did not return Operation-Location header")

        logger.info("CUAdapter: analysis submitted, polling at %s", operation_url)
        return operation_url

    def _poll_result(self, operation_url: str) -> dict:
        """Poll the CU operation until success, failure, or timeout."""
        headers = self._get_auth_headers()
        deadline = time.time() + (self._config.max_poll_minutes * 60)

        while time.time() < deadline:
            response = requests.get(operation_url, headers=headers, timeout=30)
            response.raise_for_status()
            body = response.json()

            status = body.get("status", "").lower()
            if status == "succeeded":
                return body.get("result", body)
            elif status in ("failed", "canceled"):
                error = body.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"CU analysis failed: {error}")

            time.sleep(self._config.poll_interval_seconds)

        raise TimeoutError(
            f"CU analysis did not complete within {self._config.max_poll_minutes} minutes"
        )

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------
    def _map_fields(self, raw_response: dict, result: ExtractionResult) -> None:
        """Map CU response fields to ExtractionResult using CU_FIELD_MAP."""
        # CU response structure: contents[0].fields or analyzeResult.documents[0].fields
        fields = self._extract_fields_from_response(raw_response)

        for cu_field_name, schema_path in CU_FIELD_MAP.items():
            field_data = fields.get(cu_field_name)

            if field_data is None:
                # Field not present in CU output — mark as not filled
                result.fields[schema_path] = FieldResult(
                    field_path=schema_path,
                    value=None,
                    confidence=None,
                    source="cu",
                    status="not_filled",
                )
                continue

            # Extract value and confidence from CU field structure
            value = self._extract_value(field_data)
            confidence = field_data.get("confidence", 0.5)

            result.fields[schema_path] = FieldResult(
                field_path=schema_path,
                value=value,
                confidence=confidence,
                source="cu",
                status="filled" if value is not None else "not_filled",
            )

    @staticmethod
    def _extract_fields_from_response(raw_response: dict) -> dict:
        """Navigate CU response structure to find the fields dictionary."""
        # Content Understanding format
        contents = raw_response.get("contents", [])
        if contents and isinstance(contents[0], dict):
            fields = contents[0].get("fields", {})
            if fields:
                return fields

        # Legacy Document Intelligence format
        analyze_result = raw_response.get("analyzeResult", {})
        documents = analyze_result.get("documents", [])
        if documents and isinstance(documents[0], dict):
            return documents[0].get("fields", {})

        return {}

    @staticmethod
    def _extract_value(field_data: dict) -> Any:
        """Extract the typed value from a CU field response."""
        if isinstance(field_data, dict):
            # CU returns: {"type": "string", "valueString": "...", "confidence": 0.95}
            for key in ("valueString", "valueNumber", "valueInteger",
                        "valueBoolean", "valueArray", "valueDate", "content"):
                if key in field_data:
                    return field_data[key]
            # Fallback to 'value' key
            return field_data.get("value")
        return field_data

    # ------------------------------------------------------------------
    # Authentication & URL handling
    # ------------------------------------------------------------------
    def _get_auth_headers(self) -> dict:
        """Return authorization headers — API key or bearer token."""
        if self._config.api_key:
            return {"Ocp-Apim-Subscription-Key": self._config.api_key}

        # Use DefaultAzureCredential for token-based auth
        if not self._token or (self._token_expiry and datetime.now(timezone.utc) >= self._token_expiry):
            token_result = self._credential.get_token("https://cognitiveservices.azure.com/.default")
            self._token = token_result.token
            self._token_expiry = datetime.fromtimestamp(token_result.expires_on, tz=timezone.utc)

        return {"Authorization": f"Bearer {self._token}"}

    def _ensure_accessible_url(self, blob_url: str) -> str:
        """Generate a SAS-signed URL if the blob is in private storage."""
        if not self._storage_config or "?" in blob_url:
            return blob_url  # Already has SAS or external URL

        parsed = urlparse(blob_url)
        account_name = parsed.netloc.split(".")[0]
        path_parts = parsed.path.lstrip("/").split("/", 1)

        if len(path_parts) < 2:
            return blob_url

        container_name, blob_name = path_parts

        # Generate read-only SAS token valid for 30 minutes
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_name,
            credential=self._credential,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

        return f"{blob_url}?{sas_token}"
