# 6. Vision Bridge exposes one Qwen3-VL-Plus image-analysis tool

Date: 2026-08-17

## Status

Accepted. This supersedes the previous two-tool design.

## Decision

The static Vision Bridge MCP contract contains exactly one tool:

```text
vision_analyze_image(image_path)
```

`image_path` must identify a supported local image. The tool is fixed to
`qwen3-vl-plus` and returns a description of visible non-textual content.
There is no intent parameter, OCR route, model override, document tool, or
fallback behavior.

## Consequences

- Tool selection is deterministic: a supported image path maps to the one
  Vision Bridge tool; every other task uses another appropriate MCP server.
- The generated manifest is the source of truth for `tools/list`; callers and
  the Image Guard must not retain historical tool names.
- The narrow schema makes version-skew explicit and prevents a desktop client
  from silently sending a request to a removed route.
