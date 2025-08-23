from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Tuple


_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F<>:\\/\|\?\*"]+")
_MULTIPLE_UNDERSCORES_RE = re.compile(r"_+")

# Many filesystems have a 255 byte/char filename limit per path segment.
_MAX_SEGMENT_LEN = 255


def _sanitize_segment(name: str, *, preserve_ext: str | None = None) -> str:
    """Sanitize a single path segment to be cross-filesystem safe.

    - Normalize Unicode to NFC
    - Replace illegal characters with '_'
    - Trim trailing spaces/dots (NTFS/SMB safety)
    - Collapse multiple underscores
    - Enforce max length per segment (preserving extension if provided)
    - Ensure not empty
    """
    original = name
    s = unicodedata.normalize("NFC", name)
    # Replace illegal characters
    s = _ILLEGAL_CHARS_RE.sub("_", s)
    # Trim trailing spaces/dots
    s = s.rstrip(" .")
    # Avoid entirely empty names
    if not s:
        s = "_"
    # Collapse consecutive underscores
    s = _MULTIPLE_UNDERSCORES_RE.sub("_", s)

    # Enforce max length; try to preserve extension if provided
    if len(s) > _MAX_SEGMENT_LEN:
        if preserve_ext and s.lower().endswith(preserve_ext.lower()) and len(preserve_ext) < _MAX_SEGMENT_LEN:
            base_len = _MAX_SEGMENT_LEN - len(preserve_ext)
            s = s[:base_len] + preserve_ext
        else:
            s = s[:_MAX_SEGMENT_LEN]
    return s


def sanitize_rel_path(rel: Path, *, final_suffix: str = ".m4a") -> Path:
    """Sanitize a relative path for the destination tree and set the final suffix.

    The input may have any suffix; we enforce `final_suffix` on the last part.
    Each segment is sanitized to be safe across common filesystems.
    """
    # Ensure it's a relative path (but keep behavior if absolute by making it relative-like)
    parts = list(rel.parts)
    # Apply suffix change to filename
    if parts:
        p = Path(parts[-1]).with_suffix(final_suffix)
        parts[-1] = p.name
    safe_parts: List[str] = []
    for i, seg in enumerate(parts):
        # Only the last segment needs to preserve the extension
        preserve_ext = None
        if i == len(parts) - 1:
            # Extract extension from the segment as provided
            dot = seg.rfind('.')
            preserve_ext = seg[dot:] if dot != -1 else None
        safe_parts.append(_sanitize_segment(seg, preserve_ext=preserve_ext))
    return Path(*safe_parts)


def _existing_rel_paths(out_root: Path) -> set[Path]:
    """Return a set of already-present relative file paths under out_root."""
    existing: set[Path] = set()
    if not out_root.exists():
        return existing
    for dirpath, _, filenames in os.walk(out_root):
        d = Path(dirpath)
        for fn in filenames:
            try:
                rel = (d / fn).relative_to(out_root)
            except Exception:
                continue
            existing.add(rel)
    return existing


def resolve_collisions(
    candidates: Iterable[Path],
    *,
    out_root: Path,
) -> List[Path]:
    """Resolve duplicate destination paths deterministically.

    Strategy:
    - Start from sanitized candidates (but we sanitize again defensively).
    - Build a taken set including existing files under `out_root`.
    - For each candidate in stable, sorted order of its string path, if taken, append
      " (n)" before the extension, incrementing n starting at 1, until unique.
    - Truncate if needed to keep within per-segment limits while preserving extension.
    """
    taken: set[Path] = _existing_rel_paths(out_root)
    result: List[Tuple[str, Path]] = []  # (key for stable ordering, resolved path)

    # Prepare inputs with stable keys
    items: List[Tuple[str, Path]] = [(str(p), sanitize_rel_path(p)) for p in candidates]
    # Sort deterministically by the original planned path string
    items.sort(key=lambda t: t[0])

    resolved_map: dict[str, Path] = {}

    for key, cand in items:
        # Ensure path parts are safe
        cand = sanitize_rel_path(cand)
        final = cand
        if final in taken or final in (p for _, p in result):
            # Compute suffixed variants
            stem = final.stem
            ext = final.suffix
            parent = final.parent
            n = 1
            while True:
                suffix = f" ({n})"
                new_name = _sanitize_segment(stem + suffix + ext, preserve_ext=ext)
                candidate = parent / new_name
                if candidate not in taken and candidate not in (p for _, p in result):
                    final = candidate
                    break
                n += 1
        taken.add(final)
        result.append((key, final))
        resolved_map[key] = final

    # Return results in the original input order
    return [resolved_map[str(p)] for p in candidates]
