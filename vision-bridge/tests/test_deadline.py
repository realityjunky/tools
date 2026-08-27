from __future__ import annotations

import time
from types import SimpleNamespace

from vision_bridge.deadline import DEADLINE_META_KEY, deadline_from_context


def test_node_deadline_metadata_is_preserved_for_the_python_gateway() -> None:
    expires_at_ms = int((time.time() + 90) * 1_000)
    context = SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(
                params=SimpleNamespace(
                    meta={
                        DEADLINE_META_KEY: {
                            "deadline_unix_ms": expires_at_ms,
                            "request_id": "d0b3b29c-37aa-4dd1-9ac4-bb0f3e0a2f78",
                        }
                    }
                )
            )
        )
    )

    deadline = deadline_from_context(context, fallback_timeout_seconds=120)

    assert deadline.request_id == "d0b3b29c-37aa-4dd1-9ac4-bb0f3e0a2f78"
    assert deadline.expires_at_epoch_seconds == expires_at_ms / 1_000


def test_invalid_deadline_metadata_falls_back_to_the_local_request_budget() -> None:
    before = time.time()
    context = SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(
                params=SimpleNamespace(meta={DEADLINE_META_KEY: {"deadline_unix_ms": "bad"}})
            )
        )
    )

    deadline = deadline_from_context(context, fallback_timeout_seconds=5)

    assert before + 4 <= deadline.expires_at_epoch_seconds <= time.time() + 5
    assert deadline.request_id is None
