# 4. Vision Bridge is isolated from OCR and document parsing

Date: 2026-08-17

## Status

Accepted. This replaces the earlier multi-purpose Vision Bridge design.

## Context

An MCP server that selects several models and routes both images and documents
has a broad, fragile configuration contract. Old desktop configuration can keep
using an obsolete tool shape even when a new package has been installed.

## Decision

Vision Bridge is a fixed, visual-image-analysis MCP server:

- It exposes only `vision_analyze_image(image_path)`.
- It always uses `qwen3-vl-plus`.
- It accepts only supported local raster-image paths.
- It does not offer OCR, text extraction, table-cell reading, PDF handling, or
  document parsing.
- It does not invoke MinerU, accept MinerU credentials, or contain a MinerU
  fallback. OCR users configure MinerU MCP separately in their desktop client.

## Consequences

- A document or text-reading task is outside the Vision Bridge contract, even
  if the file contains images.
- The Image Guard redirects only supported image paths to Vision Bridge; it
  never emits a document-oriented Vision Bridge tool name.
- Generated desktop configuration contains a revision marker. A stale
  configuration fails clearly instead of silently selecting old behavior.
