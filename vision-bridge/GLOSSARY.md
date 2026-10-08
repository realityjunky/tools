# Vision Bridge Context

Vision Bridge is the standalone local MCP tool maintained in this project. Its
context owns the tool's identity, client-facing contract, and tool-specific
architectural decisions.

The Platform Control Plane context in the parent `hugo_AI` repository owns
shared identity, authorization, model catalog, provider deployment, and
gateway policy. Vision Bridge integrates with those capabilities but does not
own their domain language or governance.

## Language

**Vision Bridge**:
The standalone local MCP tool whose identity, client-facing contract, and
tool-specific architectural decisions are owned by this context.

**Platform Control Plane**:
The parent context that owns shared identity, authorization, model catalog,
provider deployment, and gateway policy.
