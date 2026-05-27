"""
Azure Architecture Diagram Generator for Document Extraction Pipeline
Generates PNG, DOT, and Draw.io format diagrams

Architecture:
- Azure Blob Storage (PDF staging + extraction results)
- Azure Content Understanding (S0 — deterministic OCR/field extraction)
- Azure OpenAI GPT-5.2 (bounded gap-fill verification)
- Azure Cosmos DB Serverless (persistence + deduplication)
- Azure Service Bus Basic (event-driven queues)
- Application Insights + OpenTelemetry (observability)
- Confidence-based routing: auto-accept / agent-review / human-review
"""

import subprocess
from diagrams import Diagram, Cluster, Edge
from diagrams.azure.database import CosmosDb
from diagrams.azure.storage import BlobStorage
from diagrams.azure.integration import ServiceBus
from diagrams.azure.devops import ApplicationInsights
from diagrams.azure.aimachinelearning import CognitiveServices, AzureOpenai
from diagrams.azure.security import KeyVaults
from diagrams.onprem.client import Users
from diagrams.programming.language import Python

# ===========================================================================
# Document Extraction Pipeline — System Architecture
# ===========================================================================
with Diagram(
    "Document Extraction Pipeline — System Architecture",
    filename="diagrams/document_extraction_system",
    outformat=["png", "dot"],
    show=False,
    direction="TB",
    graph_attr={
        "splines": "spline",
        "nodesep": "1.0",
        "ranksep": "1.5",
        "fontsize": "14",
        "bgcolor": "white",
        "pad": "0.6",
        "dpi": "300",  # High resolution output (300 DPI)
    }
):
    # External user
    users = Users("Document\nUpload")

    # 1. Ingestion
    with Cluster("Ingestion", graph_attr={
        "fontsize": "13", "bgcolor": "#E3F2FD", "style": "rounded", "margin": "20", "labelloc": "t"
    }):
        blob_in = BlobStorage("Blob Storage\npdf-staging")

    # 2. Extraction
    with Cluster("Deterministic Extraction", graph_attr={
        "fontsize": "13", "bgcolor": "#E8F5E9", "style": "rounded", "margin": "20", "labelloc": "t"
    }):
        cu = CognitiveServices("Azure Content Understanding (S0)\n107 Fields · Per-field Confidence")

    # 3. Processing (center hub)
    with Cluster("Processing & AI Enhancement", graph_attr={
        "fontsize": "13", "bgcolor": "#FFF8E1", "style": "rounded", "margin": "20", "labelloc": "t"
    }):
        pipeline = Python("Pipeline Orchestrator\nNormalize → Validate → Route")
        openai = AzureOpenai("Azure OpenAI GPT-5.2\nGap-Fill · Temp=0.0 · JSON")
        agent = AzureOpenai("Exception Agent\nCORRECT / ACCEPT / ESCALATE")

    # 4. Routing outputs
    with Cluster("Confidence Routing", graph_attr={
        "fontsize": "13", "bgcolor": "#FFEBEE", "style": "rounded", "margin": "20", "labelloc": "t"
    }):
        cosmos = CosmosDb("Cosmos DB (Serverless)\nAuto-Accept ≥0.85\nAgent Review 0.60–0.84")
        servicebus = ServiceBus("Service Bus\nHuman Review <0.60")

    # 5. Output
    with Cluster("Output & Storage", graph_attr={
        "fontsize": "13", "bgcolor": "#F3E5F5", "style": "rounded", "margin": "20", "labelloc": "t"
    }):
        blob_out = BlobStorage("Blob Storage\nextraction-results")

    # Cross-cutting
    with Cluster("Observability", graph_attr={
        "fontsize": "13", "bgcolor": "#F1F8E9", "style": "rounded", "margin": "14", "labelloc": "t"
    }):
        appinsights = ApplicationInsights("Application Insights\nOpenTelemetry")

    with Cluster("Security", graph_attr={
        "fontsize": "13", "bgcolor": "#FCE4EC", "style": "rounded", "margin": "14", "labelloc": "t"
    }):
        keyvault = KeyVaults("Key Vault\nManaged Identity · RBAC")

    # === Strictly linear flow (no back-edges) ===
    users >> Edge(label="Upload PDF") >> blob_in
    blob_in >> Edge(label="Submit Analysis") >> cu
    cu >> Edge(label="Structured Fields + Confidence") >> pipeline

    # AI within same cluster — no back-edges needed
    pipeline >> Edge(label="Gap Fields", style="dashed") >> openai
    pipeline >> Edge(label="Edge Cases", style="dashed", color="orange") >> agent

    # Routing
    pipeline >> Edge(label="≥0.85 Auto-Accept", color="green") >> cosmos
    pipeline >> Edge(label="<0.60 Human Review", color="red") >> servicebus

    # Persistence to output
    cosmos >> Edge(label="Final Records") >> blob_out

    # Cross-cutting (clean side connections)
    pipeline >> Edge(label="Telemetry", style="dotted", color="green") >> appinsights
    pipeline >> Edge(label="Secrets", style="dotted", color="gray") >> keyvault


print("✓ PNG and DOT files generated in diagrams/")

# Convert DOT to Draw.io format
try:
    subprocess.run([
        "graphviz2drawio",
        "diagrams/document_extraction_system.dot",
        "-o",
        "diagrams/document_extraction_system.drawio"
    ], check=True)
    print("✓ Draw.io file generated: diagrams/document_extraction_system.drawio")
except subprocess.CalledProcessError as e:
    print(f"✗ Failed to convert to Draw.io: {e}")
except FileNotFoundError:
    print("✗ graphviz2drawio not found. Install with: pip install graphviz2drawio")

print("\nGenerated files:")
print("  - diagrams/document_extraction_system.png")
print("  - diagrams/document_extraction_system.dot")
print("  - diagrams/document_extraction_system.drawio")
