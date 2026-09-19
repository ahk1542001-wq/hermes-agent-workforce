from hermes_job_scout.redaction import redact_data, redact_text


def test_secret_text_is_redacted() -> None:
    text = (
        "api_key=sk-test-12345678901234567890 contact person@example.com "
        "phone +66 81 234 5678 path /Users/example/Private/Career token=abc123456789xyz"
    )
    redacted = redact_text(text)
    assert "sk-test" not in redacted
    assert "person@example.com" not in redacted
    assert "81 234" not in redacted
    assert "/Users/example" not in redacted
    assert "abc123" not in redacted
    assert redacted.count("<REDACTED>") >= 5


def test_structured_secret_keys_are_redacted_recursively() -> None:
    value = {
        "provider": "synthetic",
        "access_token": "secret-value",
        "nested": {"password": "hidden", "count": 2},
    }
    assert redact_data(value) == {
        "provider": "synthetic",
        "access_token": "<REDACTED>",
        "nested": {"password": "<REDACTED>", "count": 2},
    }
