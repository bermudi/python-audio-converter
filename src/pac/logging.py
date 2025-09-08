from __future__ import annotations
import sys
import uuid
from typing import Optional, Any, Dict
from loguru import logger

_configured = False

def setup_console(level: str = "INFO") -> None:
    global _configured
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), enqueue=True, backtrace=False, diagnose=False)
    _configured = True

def setup_json(path: str, level: str = "DEBUG") -> None:
    logger.add(path, level=level.upper(), serialize=True, enqueue=True)

def setup_qt_sink(emitter, level: str = "INFO", json_path: Optional[str] = None) -> None:
    global _configured
    logger.remove()
    fmt = "<level>{level: <8}</level> | <green>{time:HH:mm:ss}</green> | <cyan>{message}</cyan>"
    def qt_sink(msg: "loguru.Message"):
        try:
            text = msg.record.get("message", str(msg))
            emitter.message.emit(str(text).rstrip())
        except Exception:
            pass
    logger.add(qt_sink, level=level.upper(), format=fmt, enqueue=True)
    logger.add(sys.stderr, level=level.upper(), format=fmt, enqueue=True, backtrace=False, diagnose=False)
    if json_path:
        setup_json(json_path)
    _configured = True

def bind_run(run_id: Optional[str] = None) -> str:
    rid = run_id or str(uuid.uuid4())
    # Use configure to apply extra fields to all loggers.
    logger.configure(extra={"run_id": rid})
    return rid

def get_logger():
    return logger

def log_event(action: str, **fields: Any) -> None:
    # Strip None, truncate large lists/strings
    clean: Dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
    msg = clean.pop("msg", action)
    level = clean.pop("level", "INFO").upper()
    logger.bind(action=action, **clean).log(level, msg)


def truncate(text: str, max_len: int = 4096, max_lines: int = 20) -> str:
    """Truncate a string to a max length and/or max number of lines."""
    if not text:
        return ""
    # Limit lines first
    lines = text.strip().splitlines()
    if len(lines) > max_lines:
        text = "\n".join(["... (truncated)"] + lines[-max_lines:])

    # Then limit length
    if len(text) > max_len:
        text = "... (truncated)\n" + text[-max_len:]
    return text
