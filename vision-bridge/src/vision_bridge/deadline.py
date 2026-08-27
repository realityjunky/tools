"""One request deadline shared by the Node proxy and Python gateway."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vision_bridge.errors import RequestDeadlineExceeded

DEADLINE_META_KEY = "io.hugobiotech/vision-bridge"
_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f-]{8,64}$")


@dataclass(frozen=True, slots=True)
class RequestDeadline:
    """A wall-clock deadline, rather than a chain of independent timeouts."""

    expires_at_epoch_seconds: float
    request_id: str | None = None

    def remaining_seconds(self) -> float:
        remaining = self.expires_at_epoch_seconds - time.time()
        if remaining <= 0:
            raise RequestDeadlineExceeded("Vision Bridge request deadline exceeded")
        return remaining


def deadline_from_context(
    context: object | None,
    *,
    fallback_timeout_seconds: float,
) -> RequestDeadline:
    """Read proxy metadata and cap it to the configured local deadline."""

    now = time.time()
    fallback_expires_at = now + fallback_timeout_seconds
    metadata = _request_metadata(context)
    bridge_metadata = metadata.get(DEADLINE_META_KEY)
    if not isinstance(bridge_metadata, Mapping):
        return RequestDeadline(expires_at_epoch_seconds=fallback_expires_at)

    propagated_expires_at = _deadline_epoch_seconds(bridge_metadata.get("deadline_unix_ms"))
    expires_at = (
        min(propagated_expires_at, fallback_expires_at)
        if propagated_expires_at > 0
        else fallback_expires_at
    )
    request_id = bridge_metadata.get("request_id")
    return RequestDeadline(
        expires_at_epoch_seconds=expires_at,
        request_id=request_id
        if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id)
        else None,
    )


def _request_metadata(context: object | None) -> Mapping[str, Any]:
    if context is None:
        return {}
    request_context = getattr(context, "request_context", None)
    request = getattr(request_context, "request", None)
    params = getattr(request, "params", None)
    metadata = getattr(params, "meta", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _deadline_epoch_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) / 1_000
