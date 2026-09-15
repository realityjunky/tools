# 5. Image Guard redirects to the Vision Bridge instead of captioning

Date: 2026-08-06

## Status

**Retired 2026-09-11. The mechanism this ADR describes no longer exists.**

The platform retired its model-governance capability blobs and the text/vision key split, and the
Image Guard's whole image ladder went with them: multi-format detection, Path Recovery, Redirect,
Caption Fallback, and Instructional Text. The gateway hook now enforces External API Entitlements
and redacts LightRAG provider spans; it does not inspect image content. The Vision Bridge itself is
unaffected — it remains installable and usable as a user-invoked tool — but nothing redirects a
model into it any more.

The consequence below still stands, inverted. An image bound for a Text Model is now forwarded to
the provider as sent, rather than refused or substituted, so a provider that accepts image input
and answers anyway reproduces precisely the confident answer about an unseen image that this ADR
was written to prevent. That trade was made deliberately, alongside the retirement of the per-model
capability classification this Guard was built on.

Everything below is preserved as written. It described the mechanism accurately from its
implementation on 2026-08-07 until its removal on 2026-09-11.

## Original status

Accepted. Revises the captioning behaviour accepted in [ADR-0002](0002-two-tier-image-input-for-text-only-models.md).

Amended 2026-08-06 with the multi-format detection finding, the three-route Path Recovery
asymmetry, and the resolution of the alias-set gap. The decision is unchanged.

Implemented 2026-08-07. Detection over every image shape landed in issue #178; Path Recovery
and Redirect in issue #180; Caption Fallback in issue #181. The detection gate recorded in the
consequences is satisfied, and the consequences now also record the two-signal Redirect gate
and the path-hashing rule. All three rungs of the ladder this ADR describes are implemented, so
Instructional Text is now the floor beneath a failed Caption rather than the only fallback.

All three are also *live*, in the sense this document uses the word everywhere else: verified
against the running gateway at named commits. Detection and Redirect were verified at merge
commit `7572437`. Caption Fallback was verified 2026-08-07 at merge commit `7121627`, after the
gateway was recreated and the host and container Guard inodes matched. A real 395x395 image
submitted from the LiteLLM Playground prompt composer to `deepseek-official-v4-flash` returned
an answer grounded in the caption. The audit line independently recorded `format=openai_data_url`,
`path_recovered=no`, `outcome=caption`, and `caption=ok`; it contained dimensions and hashes,
not image or caption content.

Caption Fallback is inert until a deployment is given a managed Image Guard ServiceAccount
credential (`IMAGE_GUARD_LITELLM_SERVICE_ACCOUNT_KEY` or
`IMAGE_GUARD_LITELLM_SERVICE_ACCOUNT_KEY_FILE`). That is a supported configuration and not a
partial implementation — without it every image degrades to Instructional Text, exactly as
before the feature existed — but it is reported at CRITICAL on startup, because a rotated-out
credential is indistinguishable from an absent one from inside the Guard and both degrade every
user of every Text Model at once. The former `IMAGE_GUARD_LITELLM_VIRTUAL_KEY` target is ignored
and Compose neutralizes it during the replacement-first migration.

## Context

A user's agent can put an image in front of a Text Model two ways, and they are not
equally recoverable.

When the client's own file reader handles an image, the request still contains the path.
On the Anthropic route the two blocks are linked by an ID:

```json
{"type": "tool_use",    "id": "toolu_x", "name": "Read",
 "input": {"file_path": "/home/hugo/shot.png"}}
{"type": "tool_result", "tool_use_id": "toolu_x",
 "content": [{"type": "image", "source": {"type": "base64", "...": "..."}}]}
```

When the user pastes an image, it arrives in a plain user message with no originating tool
call and no path anywhere in the request.

So the absence of a recoverable path is itself the signal that an image was pasted. The
two cases separate on a deterministic join, not a heuristic.

Captioning both cases — ADR-0002's behaviour — serves the lossy path even when the good
one was available, and spends platform credit doing it.

## Decision

The Image Guard attempts Path Recovery first. When it recovers a path, it performs a
Redirect. Only when no path is recoverable does it fall back to a Caption.

A Redirect is a **text substitution, not an HTTP error**. The image content block is
replaced in place with text naming the tool and the path:

```
[Image at /home/hugo/shot.png was not sent to this model.
 Call vision_analyze_image with image_path=/home/hugo/shot.png to read it.]
```

The request then proceeds to the Text Model normally.

A Redirect is issued only when the request's `tools` array actually contains a Vision Bridge
tool that can open the recovered file, matched on name suffix so that any server naming
convention resolves — Claude Code exposes MCP tools as `mcp__<server>__<tool>`. The Bridge
exposes one image-only tool, `vision_analyze_image`, which accepts a supported local image
path as `image_path`. Documents are not Vision Bridge input. With no matching image tool
present, the Guard captions instead, and Caption text carries a pointer to the Bridge so the
user learns why the answer was degraded and how to fix it.

When the Caption itself fails, the Guard substitutes instructional text rather than failing the
request:

```
[Image could not be read: the vision service is unavailable.
 Do not infer its contents. Tell the user to retry, or to save the
 image and call vision_analyze_image with its path.]
```

It retries once first, but only for failures a second attempt could actually clear. An earlier
revision of this ADR named "provider timeout, exhausted quota, a credential mid-rotation" as the
retry cases; the implementation retries the timeout and refuses the other two, and the narrowing
is correct rather than a divergence to reconcile. A quota that is exhausted and a key that has
been rotated out both fail the second attempt for the same reason they failed the first, so the
retry buys nothing and spends the wait twice — and both are conditions that hit every user of
every Text Model simultaneously, which is precisely when doubling the added latency is worst. The
classification is a single table in the Guard rather than a check at each call site, so a new
failure reason cannot quietly default into retrying.

A credential failure is logged at error level and alerted on. A rotated-out platform
credential degrades every user at once and is the platform's bug, not a provider's, so it must
not hide inside a per-request degradation.

Key grants are deliberately not consulted. The Bridge authenticates with its own External API
Key from MCP configuration, so the text key's alias grants carry no information about whether
the Bridge can reach a Vision Model. Tool presence is the only honest signal in the request.

## Consequences

An error response aborts the turn and surfaces to the human, so the model never sees it and
cannot self-correct. A substitution lands in the conversation as model-visible text, so the
model reads the instruction and calls the Vision Bridge on its next turn. This distinction
is the whole mechanism; an implementation that raises `HTTPException` does not deliver the
behaviour this ADR accepts.

Path Recovery is route-asymmetric across the three routes the gateway exposes, all of which
are in scope:

- `/v1/messages` — **exact**. The `tool_use_id` join is deterministic.
- `/v1/responses` — **exact or positional, at the client's choice**. `function_call_output.output`
  accepts an item list holding `input_image`, so a client may return the read image inside the
  output that names its call by `call_id` — an exact join, the same quality `/v1/messages` gets.
  Emitting the image as a separate `input_image` item is equally legal and leaves only position to
  join on. Corrected 2026-08-07; see the window discussion below for what the earlier reading of
  this route cost.
- `/v1/chat/completions` — **best-effort**. The tool-result role carries a string rather than
  image parts, so a client that has read an image must inject it as a user message, often
  with no tool call to join back to.

Claude Code uses the Anthropic route, so the reliable case covers the primary client. The
asymmetry is inherent to the formats and is accepted rather than equalised.

Path extraction must not key on a single argument name. The example above shows Claude Code's
`Read` tool with `file_path`, but other clients and other tools name the argument
differently, so recovery reads whichever argument value is path-shaped and carries a
supported extension. Hardcoding `file_path` or the tool name `Read` would make the join work
for one client only.

Verified 2026-08-06 against the running gateway (litellm 1.83.10): the `CustomLogger`
dispatch in `ProxyLogging.pre_call_hook` applies no call-type filter, and `/v1/messages`
maps to `CallTypes.anthropic_messages`, so the Guard receives the raw Anthropic body on the
route Claude Code uses. The join is reachable in production, not just in principle.

**The mechanism did not fire on its own best route until detection was widened.** Resolved
2026-08-07: detection landed in issue #178 and Redirect in issue #180, in that order and for
the reason set out here. The finding is kept rather than deleted because it is why the two
shipped separately, and because a silent drop is the first thing to check for if the
mechanism ever goes quiet again.

Verified 2026-08-06 against the running gateway: the Guard matched only `type: "image_url"`,
the OpenAI shape. Claude Code sends the Anthropic-native shape,
`{"type": "image", "source": {...}}`, which the Guard did not recognise:

```
/v1/messages + Anthropic native image  -> 200 OK, input_tokens=10   image silently dropped
/v1/messages + OpenAI image_url        -> 400, guard fires
/v1/chat/completions + image_url       -> 400, guard fires
```

So on `/v1/messages` — the one route where this ADR's join is exact — nothing was detected,
the image was dropped by the provider, and the model answered confidently about an image it
never saw. On the primary client that failure is a hallucination, not a refusal, which is
worse than the error this ADR set out to replace.

Redirect was therefore gated on detection covering all five shapes an image can arrive in:
`image_url` with a data URL, `image_url` with a remote URL, Anthropic `image` with a base64
source, Anthropic `image` with a URL source, and Responses `input_image`. `file_id`
references count wherever they are permitted; `/v1/files` is confirmed exposed on the
gateway, so uploaded-file images can genuinely arrive. A Redirect built on the old detection
would have been dead code on the route it matters most on. Issue #174 sequenced detection
ahead of Redirect for this reason, and both are now delivered.

Redirect requires two things present in the same request, and falls back to Instructional
Text when either is missing. A recovered path with no Bridge tool would name a tool the model
cannot call, and a Bridge tool with no recovered path would have no argument to offer it;
either way the model spends a turn to reach a dead end, which is worse than being told plainly
that an image could not be read. The two absences are logged separately (`path_recovered=`
and `bridge_tool=`) because the outcome alone cannot distinguish a client shipping no Bridge
from a paste the join could never have resolved.

Verified end to end 2026-08-07 against the running gateway **at merge commit `7572437`**, on all
three routes rather than only the exact one, across thirteen cases each asserting both the Guard's
audit line and the delivered reply — all thirteen returned a model reply, so no case rests on the
audit line alone. A tool-read image plus a declared Bridge tool returned 200 and the
Text Model reissued the work as `mcp__vision-bridge__vision_analyze_image` with the recovered
`image_path` — on `/v1/messages`, on `/v1/chat/completions` where the join is positional, and
on `/v1/responses` where the substituted `input_text` part was accepted rather than rejected.
Both absences were exercised on the same alias: with no Bridge tool declared, and with a
pasted image, the model answered that it could not see the image and named no path and no
tool. That is the behaviour this ADR is for — the earlier failure on this route was a
confident answer about an unseen image, so an honest refusal is the fix, and it is what the
fallback now produces in production.

The in-output join is included: an image returned inside `function_call_output.output` was joined by
`call_id` and redirected live, the shape this ADR's earlier `str` error had left undetected. An
interim revision scoped this claim to commit `95aa513` and excluded that shape, because the walk
landed afterwards and the gateway loads this Guard from a bind mount. Both conditions are now
satisfied — the merge carried the file to `/home/hugo/AI` and the container was recreated — so the
exclusion is lifted rather than left standing.

A single-file bind mount is worth recording as an operational hazard, since it is why the exclusion
existed at all. The mount pins an **inode**, not a path, and git replaces files by rename rather than
in place, so every merge or checkout leaves the container holding the pre-merge file while the host
shows the new one. Nothing restarts and nothing warns; the gateway simply keeps running old code.
`docker compose up -d --force-recreate --no-deps litellm` re-resolves it — `--force-recreate` because
compose sees no config change and would otherwise no-op, and `--no-deps` so the database and Redis
are not restarted alongside. Confirm by comparing `stat -c %i` on both sides rather than trusting
mtime. Note also that the compose service is `litellm`; `litellm-proxy` is only its `container_name`,
and naming the container is a `no such service` error.

One incidental confirmation from the same run: inside the container the Guard logs
`capability_source: portal-auth-catalog` with four text-only and six vision aliases, matching the
bundled snapshot exactly. The CRITICAL fail-open path seen when running the suite from the host is a
consequence of `portal-auth:8000` being a Docker-network hostname the host cannot resolve, not a
defect — the same code reaches the catalog from inside the network.

**Recovering the wrong path is worse than recovering none**, and that is the failure mode the
positional join invites rather than a hypothetical. A Redirect naming a file the user never
attached reads as correct, so the model opens it and answers from it; Instructional Text at least
tells the truth. Review of the first implementation found four ways to reach it, all fixed
2026-08-07 and each pinned by a test:

- A single-slot pending path attached the *last* call's file to the first image in a parallel
  two-read turn, and left the second image with none — so a compare-these-two-screenshots turn,
  which is ordinary rather than adversarial, reported a comparison fabricated from one file read
  twice. The pending paths are a queue, consumed in declaration order.
- Only an assistant turn cleared the pending path, but on Chat Completions a `tool` role is what
  follows a call, so a *failed* read left its path live indefinitely and the next pasted image
  inherited it. Any message that does not continue the turn now clears it.
- A Responses `function_call` carries both an `id` and a `call_id`, and it is `call_id` that
  `function_call_output` names. Registering whichever came first keyed the map under the ID no
  lookup would ever use, so this route's ID-assisted join silently degraded to the positional one —
  invisible while reads are sequential, wrong the moment two interleave. Every ID a call carries is
  registered.
- On Chat Completions a failed read and a successful one produce structurally identical messages:
  call, result, then a user message carrying the image. Only the result's prose differs, which the
  Guard has no business pattern-matching. What differs structurally is the carrier — a client
  injecting a read image must synthesise a message for it, because the `tool` role cannot hold
  image parts, and what it synthesises holds the image and nothing else. Prose beside an image
  therefore means a person wrote the message, and a person's image is a paste.

That last one narrows the best-effort join rather than repairing it, and the cost is explicit: a
client that captions its injected image now gets Instructional Text instead of a Redirect. That is
the safe direction, and it is confined to the route this ADR already calls best-effort — the exact
join on `/v1/messages` is unaffected, since a `tool_result` names the call whose argument carries
the path and does not care who wrote the surrounding message.

**One window survives on the two positional routes, and it cannot be closed by any rule reading
structure.** A prose-less image arriving directly after a string tool result still claims that
read's path. The carrier heuristic cannot see it, because there is nothing there to see: a string
result followed by a message holding only an image is the same bytes whether a client injected a
read image or a person pasted one. Only the result's prose distinguishes them, and pattern-matching
provider error strings is precisely what the Guard must not do. Any rule admitting the legitimate
injection admits the paste with it.

The two routes arrive at that position for different reasons, and an earlier revision of this ADR
got the second one wrong. Corrected 2026-08-07 against the running gateway, reading openai 2.24.0's
own TypedDicts rather than reasoning about what clients might send:

- `/v1/chat/completions` — **forced**. `ChatCompletionToolMessage.content` is `str` or text parts,
  so a client that read an image has no other shape available to it.
- `/v1/responses` — **chosen**. `FunctionCallOutput.output` is
  `Union[str, ResponseFunctionCallOutputItemListParam]`, and that list admits
  `ResponseInputImageContentParam` — so a tool result on this route *can* hold an image, and a
  client returning one that way is joined exactly by `call_id`. Emitting the image as a sibling
  item is also legal, and a client that does so is indistinguishable from a paste. The client can
  opt out of the window; the Guard cannot close it.

This ADR previously asserted that `function_call_output.output` is a plain `str` and cited it as
verified. It is not, and the error was load-bearing: images arriving inside an `output` were not
walked at all, so they reached the Text Model undetected and were silently dropped — the
hallucination failure this ADR exists to prevent, reintroduced by the document that forbids it.
Both are fixed: the walk exists, the join is exact, and the claim is corrected here rather than
deleted, because a type read from the provider's own package is the only kind of evidence that
should have been admitted in the first place.

Kept open deliberately, against the general preference for recovering nothing over recovering
wrong, because here the two are not comparable in cost. Refusing positional claims closes the
window and takes the Redirect away from every tool-read image on both routes — measured, not
estimated: it fails eight tests, including the per-route recovery criteria this ADR and issue #180
both require. And the misdirection it prevents is bounded in a way the parallel-read bug was not:
the path came from a `read_file` the model itself issued in the same request, so the Redirect
discloses nothing the model did not already ask for, and it points at a file whose description
will visibly fail to match the image the user pasted. The four bugs above were unbounded by
contrast — they attached paths from *other* calls, or from turns long finished.

One qualification on "discloses nothing", because the window's worst case is a read that *failed*.
The client's reader could not open the file; the Bridge authenticates with its own External API Key
from MCP configuration (ADR-0006), so it is not bound by whatever stopped the client, and a
Redirect naming that path can therefore surface content the caller was refused. The bound is
narrower than "the model already asked for it": the model chose the path, and the Redirect widens
what *reading* it can reach. It is accepted because the alternative costs every tool-read Redirect
on both positional routes, and because the model chose the path from its own context rather than
receiving one it had not seen — but the honest statement of the risk is confinement, not absence,
and a Bridge that ever gains the ability to report the caller's own access decision is the thing
that would close it properly.

Tests hold this boundary rather than leaving it implicit: the two positional routes assert the
claim still happens and say why in the test itself, `/v1/messages` asserts it does not — a read
image there arrives inside the `tool_result` that names its call, so a later paste competes for
nothing — and the exact in-output join on `/v1/responses` is asserted alongside the sibling case it
does not cover, so the two shapes on one route cannot be conflated again. The queue also drains, on
both the positional and the exact path: claiming a joined path removes it from the queue, so a
consumed path cannot be reclaimed and the window is one image wide and one turn long, not every
image after a failed read. If a structural error signal ever appears on these routes, those are the
tests that should start failing.

Two path shapes are refused as unrecoverable, both of them remote-or-unopenable wearing a local
path's clothes:

- A UNC path (`//host/share/x.png`) reads as local to the `://` check and would send the Bridge to
  another host. Remote is excluded because the Bridge takes a local path, and that reason does not
  care which spelling of remote is used.
- A filename carrying `]` could close the Guard's own bracket-delimited note and have whatever
  followed it read as ordinary conversation rather than as part of the note. Refused rather than
  escaped: an escaped `\]` is still a `]` to something reading prose, and a mangled path is one the
  tool call cannot open, so escaping trades a legible injection for an unusable instruction.
  Refusing falls back to Instructional Text, which is where every other unrecoverable path already
  goes.

Recovered paths are logged as a truncated SHA-256 digest, never as strings. Recovery is
frequent and the gateway carries all platform traffic, so a plaintext trail would accumulate
a map of every user's filesystem — a privacy cost with no operational benefit, since the
digest is enough to confirm that recovery happened and to correlate repeats of the same file.

Captioning now fires only on true pastes and on callers without the Bridge, which narrows the
platform-billed spend that was the known weakness of using a platform-internal credential
(ADR-0002).

Tool-presence detection fails silently in one direction: an unrecognised naming convention
reads as "no Bridge" and degrades a user who had one installed. That is the safe direction —
a lossy answer rather than none — and the Bridge pointer in the fallback text is what keeps it
from being invisible.

That pointer ships in both lower rungs, and in both it is prose rather than an instruction: it
names the Vision Bridge and says to save the image to a file, but names no path and no tool.
Naming a path the request never carried would invent one, and naming a tool the request does not
declare is the dead-end turn the two-signal gate exists to prevent — so the pointer has to inform
the user without instructing the model. Pinned by a test on both absences, since a fallback that
silently lost the pointer would look identical to one that never promised it.

In a Caption the pointer is conditional, and the condition is which signal was missing. A
recovered path with no Bridge tool gets it: a lossless answer existed and the client could not
reach it. A true paste does not, because there is no path for a Bridge to open — the advice would
not apply to the request that triggered it. Instructional Text carries it unconditionally, since
that text is also where a *failed* Caption lands and the Guard cannot tell those two arrivals
apart by then.

The gap in `DEEPSEEK_OFFICIAL_ALIASES` made this user-visible rather than cosmetic: a user on
`deepseek-bailian-v4-flash` got a raw provider error and would have received no Redirect
either, so they would never learn the Vision Bridge exists.

Resolved 2026-08-06. The Guard's alias sets now derive from the model catalog's `capabilities`
flags, fetched from portal-auth at import. Verified live: `source: portal-auth-catalog`, four
text-only aliases and six vision aliases, with both `deepseek-bailian-v4-*` aliases guarded
for the first time. Three properties of that resolution constrain later work:

- **Classification is fail-open.** An alias is text-only only when the catalog explicitly
  declares `image_input: false` or `vision: false`. A row declaring neither is left
  unclassified and passes through unguarded, so a forgotten annotation degrades to today's
  raw provider error rather than turning a working model into a hard 400. `qwen3.7-max` and
  `GLM5.2` are deliberately unannotated and therefore unguarded.
- **Fetch failure falls back to a snapshot** bundled in the Guard's own source, logged at
  CRITICAL and reported as `capability_source: bundled-snapshot`. Startup is deliberately not
  failed: this gateway carries all platform LLM traffic — chat, embeddings, RDA, Bisheng,
  ReportReview — and the Guard is a legibility layer over an error the provider raises
  anyway, so refusing to boot would trade broad availability for better error messages.
- **Catalog rows are created but never updated** from the default rows, so adding a capability
  flag to the defaults has no effect on a live database unless the alias is also listed in the
  image-capability synced set. A stale row that loses its flag becomes unclassified and
  unguarded, and the failure is silent in the direction of no protection. Two drift tests
  guard this at commit time, one comparing the snapshot against the catalog and one asserting
  every annotated alias is in the synced set.

Alias sets freeze at import, so an admin adding a vision model in the model management UI
takes effect on the next gateway restart rather than immediately.

## Options rejected

**Always caption.** ADR-0002's behaviour. Simple, but silently takes the lossy path when the
exact one was available, and contradicts the requirement that the agent use the Bridge.

**Always refuse, never caption.** Purest separation, but breaks pasted images, which are an
accepted use case.

**Redirect without checking tool presence.** A user who never installed the Bridge would be
told to call a tool that does not exist, burning a turn to reach a dead end — worse than the
Caption they would otherwise have received.
