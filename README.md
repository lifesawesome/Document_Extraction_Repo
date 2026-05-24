# Modernizing Document Intelligence with AI-Driven Hybrid Extraction

## Article + Reference Implementation

This folder contains a comprehensive technical article and accompanying reference code for building a production-grade, AI-driven document extraction platform using Azure services.

The architecture is **industry-agnostic** — adapt it to architectural plans, insurance claims, legal contracts, medical records, financial documents, or any domain requiring structured data extraction from complex PDFs.

## Contents

- `article.md` — Full technical article (Microsoft Tech Community style)
- `src/` — Reference implementation code (configurable, generic domain)
- `infra/` — Simplified Bicep infrastructure template

## Quick Start

1. Read `article.md` for architecture understanding
2. Copy `src/` files into your project
3. Customize `schemas/target_schema.json` with your domain fields
4. Update `src/extraction/cu_adapter.py` field mapping for your CU analyzer
5. Add domain-specific rules to `src/agents/ai_schema_mapper.py` system prompt
6. Deploy infrastructure with `infra/main.bicep`
