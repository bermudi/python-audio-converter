"""Metadata helpers (stubs using standard library only).

Real tag copying will use Mutagen later; here we define placeholders.
"""
from __future__ import annotations

from pathlib import Path


def verify_basic_metadata(_dest: Path) -> bool:
    """Placeholder: verify that output file has some metadata.
    Always returns True for now.
    """
    return True


def ensure_cover_art(_dest: Path) -> bool:
    """Placeholder for embedding cover art in MP4.
    Always returns True for now.
    """
    return True
