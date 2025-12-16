"""Logging helpers shared between CLI and GUI entrypoints."""

from __future__ import annotations

from typing import Optional

import sys

from loguru import logger


def configure_logging(log_level: str = "INFO", log_json_path: Optional[str] = None) -> None:
    """Configure Loguru for human console output and optional JSON lines file."""
    logger.remove()
    # Human console sink
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    # Optional JSON lines sink
    if log_json_path:
        logger.add(log_json_path, level="DEBUG", serialize=True, enqueue=True)
