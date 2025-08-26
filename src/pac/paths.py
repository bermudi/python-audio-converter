from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Tuple


_ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x1F\x7F<>:\/\\\|\?\*"]+')
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


def _normcase_key(p: Path) -> str:
    """Return a stable, case-insensitive key for a relative path.

    Uses POSIX-style separators and Unicode casefold to model FAT/exFAT behavior.
    """
    return p.as_posix().casefold()


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
    """Resolve duplicate destination paths deterministically and case-insensitively.

    Strategy (O(n log n) due to initial sort, O(1) per membership):
    - Sanitize all candidates defensively.
    - Build a case-insensitive `taken_keys` set from existing files under `out_root`.
    - Process candidates in deterministic order (by their original string),
      ensuring uniqueness against `taken_keys` by appending " (n)" before the
      extension starting at 1. Each accepted path's normalized key is added to
      `taken_keys` to avoid collisions among planned outputs.
    - Return results in the original input order.
    """
    # Snapshot candidates to preserve original order for the return value
    cand_list: List[Path] = list(candidates)

    # Preload existing outputs and create case-insensitive key set
    existing_paths: set[Path] = _existing_rel_paths(out_root)
    taken_keys: set[str] = {_normcase_key(p) for p in existing_paths}

    # Prepare inputs with stable sort keys and sanitized forms
    prepared: List[Tuple[str, int, Path]] = []  # (sort_key, original_index, sanitized_path)
    for idx, p in enumerate(cand_list):
        sort_key = str(p)
        prepared.append((sort_key, idx, sanitize_rel_path(p)))

    # Deterministic processing order
    prepared.sort(key=lambda t: t[0])

    outputs: List[Path] = [Path()] * len(cand_list)

    for _, idx, cand in prepared:
        # Ensure path parts are safe (idempotent)
        cand = sanitize_rel_path(cand)
        final = cand
        parent = final.parent
        stem = final.stem
        ext = final.suffix

        key = _normcase_key(final)
        if key in taken_keys:
            n = 1
            while True:
                suffix = f" ({n})"
                new_name = _sanitize_segment(stem + suffix + ext, preserve_ext=ext)
                candidate = parent / new_name
                cand_key = _normcase_key(candidate)
                if cand_key not in taken_keys:
                    final = candidate
                    key = cand_key
                    break
                n += 1

        taken_keys.add(key)
        outputs[idx] = final

    return outputs
