"""Short-lived duplicate submission protection for Streamlit sessions."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, MutableMapping
from typing import Any


STATE_KEY = "_completed_submission_fingerprints"


def submission_fingerprint(action: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"action": action, "payload": dict(payload)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def is_recent_duplicate(
    state: MutableMapping[str, Any],
    action: str,
    payload: Mapping[str, Any],
    *,
    window_seconds: float = 10.0,
    now: float | None = None,
) -> bool:
    current_time = time.monotonic() if now is None else now
    completed = dict(state.get(STATE_KEY, {}))
    completed = {
        fingerprint: timestamp
        for fingerprint, timestamp in completed.items()
        if current_time - timestamp <= window_seconds
    }
    state[STATE_KEY] = completed
    fingerprint = submission_fingerprint(action, payload)
    return fingerprint in completed


def mark_completed(
    state: MutableMapping[str, Any],
    action: str,
    payload: Mapping[str, Any],
    *,
    now: float | None = None,
) -> None:
    completed = dict(state.get(STATE_KEY, {}))
    completed[submission_fingerprint(action, payload)] = (
        time.monotonic() if now is None else now
    )
    state[STATE_KEY] = completed
