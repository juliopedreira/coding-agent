from datetime import UTC, datetime
from uuid import UUID

from lincona.sessions import generate_session_id


def test_generate_session_id_format_and_uniqueness() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)

    session_id = generate_session_id(now)

    assert session_id.startswith("202501020304-")
    uuid_part = session_id.split("-", maxsplit=1)[1]
    UUID(uuid_part)  # validates UUID format

    # successive calls should differ
    assert generate_session_id(now) != generate_session_id(now)
