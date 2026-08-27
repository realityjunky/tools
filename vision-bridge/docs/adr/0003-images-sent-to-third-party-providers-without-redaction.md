# Images may be sent to third-party providers without redaction

Both image paths for text-only models (see ADR-0002) send image bytes to Alibaba DashScope.
Users of this platform work with mNGS and tNGS reports, so a screenshot pasted or referenced
for debugging can contain Patient Context. We accept this, and control it with documentation
and an audit trail rather than a technical boundary.

The reasoning is that vision does not widen the existing exposure surface: nothing today
prevents a user from pasting the same report as *text* through the same gateway to the same
provider. Images are that already-accepted decision in a different encoding. A
refuse-on-detection filter was rejected because false negatives would give false assurance
while false positives would block legitimate debugging.

## Consequences

- User-facing docs and the Vision Bridge tool descriptions must state that patient-identifying
  screenshots should not be sent.
- Both paths log that an image was processed, with dimensions and a content hash, and never
  store the image itself. This is an audit trail, not a safeguard.
- Retrofitting a self-hosted Vision Model later is disruptive once users have built the habit.
  If a customer contract ever imposes data-handling terms, this is the decision to revisit
  first, and the Describe Hook is the harder half to satisfy because it fires on inline bytes
  with no signal about the image's provenance.
