import sys
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from pac.logging import log_event, truncate, setup_console


@pytest.fixture(autouse=True)
def setup_test_logger():
    # Ensure each test starts with a clean logger sending to a known sink
    logger.remove()
    # You can add a sink here if you want to capture output for debugging tests
    # e.g., logger.add(sys.stderr, level="DEBUG")
    yield
    logger.remove()


def test_truncate_short_text():
    text = "hello world"
    assert truncate(text) == text


def test_truncate_long_text_by_len():
    text = "a" * 5000
    truncated = truncate(text, max_len=1000)
    assert len(truncated) < 1100  # a bit of leeway for the message
    assert "... (truncated)" in truncated
    assert truncated.startswith("... (truncated)")


def test_truncate_long_text_by_lines():
    text = "\n".join([f"line {i}" for i in range(30)])
    truncated = truncate(text, max_lines=10)
    assert len(truncated.splitlines()) == 11  # 10 lines + message
    assert "... (truncated)" in truncated
    assert truncated.startswith("... (truncated)")

def test_truncate_empty_string():
    assert truncate("") == ""


@patch("pac.logging.logger")
def test_log_event_strips_none_values(mock_logger):
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger

    log_event("test_action", key1="value1", key2=None, key3="value3")

    mock_logger.bind.assert_called_once_with(action="test_action", key1="value1", key3="value3")
    mock_bound_logger.log.assert_called_once_with("INFO", "test_action")


@patch("pac.logging.logger")
def test_log_event_uses_msg_and_level_from_fields(mock_logger):
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger

    log_event("test_action", msg="custom message", level="WARNING", key="value")

    mock_logger.bind.assert_called_once_with(action="test_action", key="value")
    mock_bound_logger.log.assert_called_once_with("WARNING", "custom message")


def test_json_log_includes_run_id(tmp_path):
    from pac.logging import setup_json, bind_run, get_logger
    log_file = tmp_path / "test.log"
    setup_json(str(log_file))
    run_id = bind_run()
    logger = get_logger()
    logger.info("test message")

    import json
    with open(log_file) as f:
        log_record = json.loads(f.read())

    record = log_record["record"]
    assert "extra" in record
    assert "run_id" in record["extra"]
    assert record["extra"]["run_id"] == run_id
