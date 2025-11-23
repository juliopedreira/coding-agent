"""Session utilities: ID generation and helpers.

This module currently exposes ``generate_session_id``; later steps will add
JSONL writers/readers on top of this foundation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def generate_session_id(now: datetime | None = None) -> str:
    """Return a session id in the form YYYYMMDDHHMM-uuid4.

    ``now`` exists to ease testing and determinism; it defaults to current UTC.
    """

    instant = now or datetime.now(UTC)
    timestamp = instant.strftime("%Y%m%d%H%M")
    return f"{timestamp}-{uuid4()}"


__all__ = ["generate_session_id"]
