from __future__ import annotations

"""Destination index that derives state from output files.

Scans a destination root for .m4a/.mp4/.mp4a and .opus files, reads embedded
PAC_* tags via `pac.metadata.read_pac_tags()`, and builds two indices:

- by_rel: { rel_path -> DestEntry }
- by_md5: { PAC_SRC_MD5 -> list[DestEntry] }  (dedup is deterministic by rel_path)

This supports the stateless planner by matching sources (by FLAC STREAMINFO MD5)
with existing outputs and enabling rename/retag/skip decisions without a local DB.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Optional
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .metadata import read_pac_tags


SUPPORTED_SUFFIXES = {".m4a", ".mp4", ".mp4a", ".opus"}


@dataclass(frozen=True)
class DestEntry:
    """One destination file with PAC_* tag snapshot and basic file info."""

    # Paths
    abs_path: Path
    rel_path: Path  # relative to destination root

    # Filesystem
    size: int
    mtime_ns: int
    container: str  # "mp4" or "opus" (derived from suffix)

    # PAC_* fields (may be empty when not embedded)
    pac_src_md5: str
    pac_encoder: str
    pac_quality: str
    pac_version: str
    pac_source_rel: str

    def preferred_key(self) -> Tuple[str, str]:
        """Deterministic ordering key among duplicates.

        First by rel_path string; then by container to prefer mp4 over opus for
        stable tie-breaks.
        """
        return (str(self.rel_path), "0" if self.container == "mp4" else "1")


@dataclass
class DestIndex:
    by_rel: Dict[Path, DestEntry]
    by_md5: Dict[str, List[DestEntry]]

    def get_preferred_by_md5(self, md5: str) -> DestEntry | None:
        """Return the preferred entry for a given source MD5, if any."""
        entries = self.by_md5.get(md5) or []
        if not entries:
            return None
        return sorted(entries, key=lambda e: e.preferred_key())[0]

    def all_entries(self) -> Iterable[DestEntry]:
        return self.by_rel.values()


def _container_from_suffix(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in {".m4a", ".mp4", ".mp4a"}:
        return "mp4"
    if suf == ".opus":
        return "opus"
    return "unknown"


def _iter_media_files(root: Path) -> Iterable[Path]:
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in SUPPORTED_SUFFIXES:
                yield p


def _make_entry(dest_root: Path, abs_path: Path) -> DestEntry:
    st = abs_path.stat()
    tags = read_pac_tags(abs_path)
    return DestEntry(
        abs_path=abs_path,
        rel_path=abs_path.relative_to(dest_root),
        size=st.st_size,
        mtime_ns=int(st.st_mtime_ns),
        container=_container_from_suffix(abs_path),
        pac_src_md5=tags.get("PAC_SRC_MD5", ""),
        pac_encoder=tags.get("PAC_ENCODER", ""),
        pac_quality=tags.get("PAC_QUALITY", ""),
        pac_version=tags.get("PAC_VERSION", ""),
        pac_source_rel=tags.get("PAC_SOURCE_REL", ""),
    )


def build_dest_index(dest_root: Path, max_workers: Optional[int] = None) -> DestIndex:
    """Scan destination root and build indices by rel-path and by PAC_SRC_MD5.

    - When PAC_* are missing, entries still appear in by_rel but are absent from by_md5.
    - Duplicate MD5s are kept as a list; caller may decide rename/prune policy. This
      function orders lists deterministically by `DestEntry.preferred_key()`.
    """
    dest_root = dest_root.resolve()

    by_rel: Dict[Path, DestEntry] = {}
    md5_groups: Dict[str, List[DestEntry]] = {}

    media_files = list(_iter_media_files(dest_root))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(_make_entry, dest_root, path): path for path in media_files}
        for future in as_completed(future_to_path):
            try:
                entry = future.result()
                by_rel[entry.rel_path] = entry
                if entry.pac_src_md5:
                    md5_groups.setdefault(entry.pac_src_md5, []).append(entry)
            except Exception:
                # Skip unreadable/bad files
                continue

    # Deterministic ordering of duplicates
    for md5, entries in md5_groups.items():
        md5_groups[md5] = sorted(entries, key=lambda e: e.preferred_key())

    return DestIndex(by_rel=by_rel, by_md5=md5_groups)


__all__ = ["DestEntry", "DestIndex", "build_dest_index"]
