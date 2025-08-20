"""Source scanner for FLAC files (standard library only)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional


@dataclass
class SourceFile:
    path: Path
    rel_path: Path
    size: int
    mtime_ns: int
    flac_md5: Optional[str] = None  # STREAMINFO MD5, not a full-file hash


def scan_flac_files(src_root: Path, compute_flac_md5: bool = True) -> List[SourceFile]:
    src_root = src_root.resolve()
    results: List[SourceFile] = []
    for dirpath, _, filenames in os.walk(src_root):
        for name in filenames:
            if not name.lower().endswith(".flac"):
                continue
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            rel = full.relative_to(src_root)
            md5 = None
            if compute_flac_md5:
                try:
                    md5 = read_flac_streaminfo_md5(full)
                except Exception:
                    md5 = None
            results.append(SourceFile(
                path=full,
                rel_path=rel,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                flac_md5=md5,
            ))
    return results


def read_flac_streaminfo_md5(path: Path) -> Optional[str]:
    """Read the STREAMINFO MD5 from a FLAC file without hashing the file.

    Returns a 32-hex string or None if not found.
    """
    with path.open("rb") as f:
        sig = f.read(4)
        if sig != b"fLaC":
            return None
        last = False
        while not last:
            header = f.read(4)
            if len(header) < 4:
                return None
            last = bool(header[0] & 0x80)
            block_type = header[0] & 0x7F
            length = int.from_bytes(header[1:4], "big")
            data = f.read(length)
            if len(data) < length:
                return None
            if block_type == 0:  # STREAMINFO
                if length < 34:
                    return None
                md5 = data[-16:]
                return md5.hex()
        return None
