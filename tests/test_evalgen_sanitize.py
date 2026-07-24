from regress.evalgen.sanitize import sanitize, sanitize_messages


def test_sanitize_redacts_email() -> None:
    result = sanitize("Contact me at jane.doe@example.com please")

    assert "jane.doe@example.com" not in result
    assert "[REDACTED_EMAIL]" in result


def test_sanitize_redacts_phone_number() -> None:
    result = sanitize("Call me at 555-123-4567")

    assert "555-123-4567" not in result
    assert "[REDACTED_PHONE]" in result


def test_sanitize_redacts_openai_style_key() -> None:
    result = sanitize("My key is sk-abc123def456ghi789jklmno for testing")

    assert "sk-abc123def456ghi789jklmno" not in result
    assert "[REDACTED_KEY]" in result


def test_sanitize_redacts_aws_style_key() -> None:
    result = sanitize("AWS key AKIAABCDEFGHIJKLMNOP is leaked")

    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert "[REDACTED_KEY]" in result


def test_sanitize_redacts_name_after_im() -> None:
    result = sanitize("Hi, I'm Jane Smith and I need help")

    assert "Jane Smith" not in result
    assert "[REDACTED_NAME]" in result


def test_sanitize_redacts_name_after_my_name_is_case_insensitive() -> None:
    result = sanitize("My name is John Doe, order #12345")

    assert "John Doe" not in result
    assert "[REDACTED_NAME]" in result


def test_sanitize_redacts_name_after_this_is() -> None:
    result = sanitize("this is Bob Wilson calling about my refund")

    assert "Bob Wilson" not in result
    assert "[REDACTED_NAME]" in result


def test_sanitize_leaves_ordinary_text_untouched() -> None:
    text = "The weather is nice today and my order shipped."

    assert sanitize(text) == text


def test_sanitize_empty_string_returns_empty_string() -> None:
    assert sanitize("") == ""


def test_sanitize_lowercase_name_is_not_redacted() -> None:
    # Best-effort heuristic: only catches proper-noun-shaped names, so a
    # lowercase "name" after the intro phrase isn't touched. Documented
    # limitation, not a bug — see the module docstring.
    result = sanitize("my name is jane, need help")

    assert "jane" in result


def test_sanitize_messages_redacts_text_content_only() -> None:
    messages = [
        {"role": "user", "parts": [{"type": "text", "content": "Email me at test@test.com"}]},
        {
            "role": "assistant",
            "parts": [{"type": "text", "content": "Sure thing!"}],
            "finish_reason": "stop",
        },
    ]

    result = sanitize_messages(messages)

    assert result[0]["parts"][0]["content"] == "Email me at [REDACTED_EMAIL]"
    assert result[1]["parts"][0]["content"] == "Sure thing!"
    assert result[1]["finish_reason"] == "stop"


def test_sanitize_messages_leaves_non_text_parts_untouched() -> None:
    messages = [
        {
            "role": "assistant",
            "parts": [{"type": "tool_call", "name": "get_weather", "arguments": {"city": "SF"}}],
        }
    ]

    result = sanitize_messages(messages)

    assert result == messages


def test_sanitize_messages_handles_missing_parts_key() -> None:
    messages = [{"role": "system"}]

    result = sanitize_messages(messages)

    assert result == messages
