"""CLI Entry Point — run the document extraction pipeline from the command line.

Usage:
    python main.py --blob-url "https://storage.blob.core.windows.net/staging/doc.pdf"
    python main.py --local-file "./documents/sample.pdf"
    python main.py --blob-url "..." --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from src.config import AppConfig
from src.orchestrator.pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="AI-Driven Document Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from Azure Blob Storage
  python main.py --blob-url "https://mystorage.blob.core.windows.net/pdf-staging/doc.pdf"

  # Extract from local file (uploads to staging first)
  python main.py --local-file "./documents/sample.pdf"

  # Dry run (skip persistence)
  python main.py --blob-url "..." --dry-run

  # Save output artifacts locally
  python main.py --blob-url "..." --output-dir "./output"
        """,
    )
    parser.add_argument("--blob-url", help="Azure Blob Storage URL of the document")
    parser.add_argument("--local-file", help="Local file path (will be uploaded to staging)")
    parser.add_argument("--dry-run", action="store_true", help="Skip persistence (validation only)")
    parser.add_argument("--output-dir", default="./output", help="Local directory for output artifacts")
    args = parser.parse_args()

    if not args.blob_url and not args.local_file:
        parser.error("Provide either --blob-url or --local-file")

    # Initialize configuration (reads from environment / .env file)
    config = AppConfig()

    # Initialize pipeline
    pipeline = Pipeline(config)

    # Determine blob URL
    if args.local_file:
        blob_url = _upload_local_file(args.local_file, config)
    else:
        blob_url = args.blob_url

    # Run pipeline
    logger.info("=" * 60)
    logger.info("Starting extraction pipeline")
    logger.info("Source: %s", blob_url)
    logger.info("Dry run: %s", args.dry_run)
    logger.info("=" * 60)

    result = pipeline.run(blob_url=blob_url, dry_run=args.dry_run)

    # Save output artifacts
    _save_artifacts(result, args.output_dir)

    # Print summary
    print("\n" + "=" * 60)
    print(f"Run ID:            {result.run_id}")
    print(f"Fill Rate:         {result.fill_rate:.1%}")
    print(f"Record Confidence: {result.record_confidence:.2f}")
    print(f"Decision:          {result.review_decision.value if result.review_decision else 'N/A'}")
    print(f"Stage:             {result.stage.value}")
    print(f"Fields Extracted:  {sum(1 for f in result.fields.values() if f.value is not None)}/{len(result.fields)}")
    print("=" * 60)

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")
        sys.exit(1)


def _upload_local_file(local_path: str, config: AppConfig) -> str:
    """Upload a local file to Azure Blob Storage staging container."""
    from azure.storage.blob import BlobServiceClient

    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    if config.storage.connection_string:
        blob_service = BlobServiceClient.from_connection_string(config.storage.connection_string)
    else:
        blob_service = BlobServiceClient(
            account_url=config.storage.account_url,
            credential=config.credential,
        )

    container_client = blob_service.get_container_client(config.storage.staging_container)
    blob_name = path.name

    with open(path, "rb") as f:
        container_client.upload_blob(blob_name, f, overwrite=True)

    blob_url = f"{config.storage.account_url}/{config.storage.staging_container}/{blob_name}"
    logger.info("Uploaded local file to: %s", blob_url)
    return blob_url


def _save_artifacts(result, output_dir: str) -> None:
    """Save pipeline output artifacts to local directory."""
    out_path = Path(output_dir) / result.run_id
    out_path.mkdir(parents=True, exist_ok=True)

    # Summary
    summary = {
        "run_id": result.run_id,
        "source_url": result.source_url,
        "fill_rate": result.fill_rate,
        "record_confidence": result.record_confidence,
        "review_decision": result.review_decision.value if result.review_decision else None,
        "stage": result.stage.value,
        "total_fields": len(result.fields),
        "filled_fields": sum(1 for f in result.fields.values() if f.value is not None),
        "errors": result.errors,
    }
    (out_path / "summary.json").write_text(json.dumps(summary, indent=2))

    # Gap analysis (per-field audit trail)
    gap_analysis = {
        path: field.to_dict() for path, field in result.fields.items()
    }
    (out_path / "gap_analysis.json").write_text(json.dumps(gap_analysis, indent=2, default=str))

    # Raw CU response (if available)
    if result.raw_cu_response:
        (out_path / "cu_raw_response.json").write_text(
            json.dumps(result.raw_cu_response, indent=2, default=str)
        )

    logger.info("Artifacts saved to: %s", out_path)


if __name__ == "__main__":
    main()
