"""Tests for logging configuration and the credential-redaction guard."""

import logging

from connectwise_mcp.logging_setup import configure_logging, redact


def test_redact_masks_secret_dict_keys():
    out = redact(
        {
            "Authorization": "Basic abc",
            "clientId": "guid-value",
            "Accept": "application/json",
        }
    )
    assert out["Authorization"] == "***"
    assert out["clientId"] == "***"
    assert out["Accept"] == "application/json"


def test_redact_is_case_insensitive_and_recursive():
    out = redact({"headers": {"X-CW-Private-Key": "secret"}})
    assert out["headers"]["X-CW-Private-Key"] == "***"


def test_redact_masks_basic_token_in_strings():
    token = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="  # 28-char base64
    out = redact(f"auth=Basic {token}")
    assert token not in out
    assert "***" in out


def test_redact_does_not_mask_basic_english_word():
    # "auth" is too short to be a token; prose must survive untouched.
    assert redact("Basic auth is required") == "Basic auth is required"


def test_redact_passes_through_safe_values():
    assert redact("/service/tickets") == "/service/tickets"
    assert redact(42) == 42


def test_redacted_value_not_in_log_output(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info(
            "headers=%s", redact({"Authorization": "Basic supersecret"})
        )
    assert "supersecret" not in caplog.text


def test_configure_logging_respects_levels(monkeypatch):
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        root.handlers.clear()
        configure_logging("WARNING")
        assert root.level == logging.WARNING

        root.handlers.clear()
        monkeypatch.setenv("CW_LOG_LEVEL", "DEBUG")
        configure_logging()
        assert root.level == logging.DEBUG

        root.handlers.clear()
        configure_logging("NOTALEVEL")  # invalid -> falls back to INFO
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
