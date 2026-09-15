# Two-tier image input for text-only chat models

## Status

Accepted. The two-tier structure stands. Substantially revised in later ADRs — read those for
current behaviour:

- [ADR-0004](0004-vision-bridge-depends-on-mineru-for-document-parsing.md) defines the
  Bridge's isolation from OCR and document parsing.
- [ADR-0005](0005-image-guard-redirects-to-the-vision-bridge.md) revised the caption-always
  behaviour below: the Guard recovered a path and redirected to the Bridge first, captions
  being the fallback. **Retired 2026-09-11** — neither the Guard nor the redirect exists any
  more, and ADR-0005 now records the removal and what it cost.
- [ADR-0006](0006-vision-bridge-exposes-two-tools-split-by-input-type.md) fixes the
  Bridge's tool surface at one Qwen3-VL-Plus image-analysis tool.

Terminology has settled since this was written, and then retired. The **Describe Hook** below
became the **Image Guard**, its substitution behaviour splitting into **Redirect** and
**Caption Fallback**; all three names, and the hook itself, were retired on 2026-09-11. The
`infra/portal-auth` context glossary is authoritative and records them as retired vocabulary.

Users route CLI and desktop clients at the LiteLLM gateway with a virtual key, and the
default text model (DeepSeek V4 Flash) accepts text only on both the official and Bailian
routes. Rather than force users onto a vision model for the whole session, we give the text
model two separate paths to image content, each covering a case the other structurally cannot.

**Vision Bridge** — a local MCP server on the user's machine. The text model calls it with a
local file path; the bridge reads the file, sends it to a Vision Model through the gateway,
and returns text. This is the primary, high-fidelity path: the model can re-call it with a
sharper prompt, and per-task tools can target different Vision Models.

**Describe Hook** — an `async_pre_call_hook` in the gateway that intercepts image content in
requests bound for a text-only alias, substitutes model-visible text, and forwards the
rewritten request. This is the fallback for images pasted directly into a client's prompt box,
which arrive as inline base64 and are lossy by construction.

This ADR assumed image content meant `image_url` parts on one request format. Three routes are
live — `/v1/messages`, `/v1/chat/completions`, `/v1/responses` — and an image can arrive in
five shapes across them. ADR-0005 records the shapes and the consequences of having matched
only one.

## Considered Options

A remote HTTP MCP server was rejected: MCP tool arguments are JSON Schema with no image content
type, so a remote server receives a local path as an unreadable string, and passing bytes instead
would mean the model emitting base64 into a tool call. A local stdio shim in front of a remote
server was rejected as paying both the distribution and hosting costs. Making the Describe Hook
the only mechanism was rejected because the gateway has no access to the user's filesystem;
making the Vision Bridge the only mechanism was rejected because pasted images never touch it.

## Consequences

- We now ship a client-side artifact, adding a version-skew surface that the existing
  remote-only MCP pattern (`kb-mcp`) does not have.
- Images on the Bridge path go from the user's disk to the provider without being stored on our
  infrastructure. The Hook path likewise holds them only for the duration of a request.
- The two paths give different answer quality for the same image. Users must be told the paste
  path is degraded, and substituted text must never be passed off as the model having seen the
  image. ADR-0005 narrows when the degraded path is taken at all: a caption now fires only on
  true pastes and on callers without the Bridge installed, not on every image.
- `deepseek_input_guard.py` rejected images only for the two `deepseek-official-*` aliases,
  leaving the equally text-only Bailian-routed aliases uncovered. Resolved 2026-08-06: the
  Guard's alias sets derive from the model catalog's `capabilities` flags rather than a
  hardcoded table. See ADR-0005 for the fail-open classification, the snapshot fallback, and
  the catalog reconciliation constraint that resolution carries.
- The Bridge ships as a standalone Python package the user's MCP client runs via `uvx` or
  `pipx` (ADR-0006 fixes its tool surface). It is not a `kb-mcp` backend, which is what makes
  the version-skew surface above a new cost rather than an existing one.
