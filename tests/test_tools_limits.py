from lincona.tools.limits import truncate_output


def test_no_truncation_when_within_limits() -> None:
    text = "hello\nworld\n"
    result, truncated = truncate_output(text, max_bytes=100, max_lines=10)
    assert result == text
    assert truncated is False


def test_truncates_on_byte_limit() -> None:
    text = "a" * 10
    result, truncated = truncate_output(text, max_bytes=5, max_lines=10)
    assert truncated is True
    assert result.endswith("[truncated]")
    assert len(result.splitlines()) >= 1


def test_truncates_on_line_limit() -> None:
    text = "x\n" * 5
    result, truncated = truncate_output(text, max_bytes=100, max_lines=3)
    assert truncated is True
    assert result.count("\n") <= 4  # 3 lines + marker newline
    assert result.strip().endswith("[truncated]")


def test_handles_empty_string() -> None:
    result, truncated = truncate_output("")
    assert result == ""
    assert truncated is False
