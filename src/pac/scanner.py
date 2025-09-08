"""Source scanner for FLAC files (standard library only)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from pac.db import PacDB


@dataclass
class SourceFile:
    path: Path
    rel_path: Path
    size: int
    mtime_ns: int
    flac_md5: Optional[str] = None  # STREAMINFO MD5, not a full-file hash


def scan_flac_files(
    src_root: Path,
    compute_flac_md5: bool = True,
    max_workers: Optional[int] = None,
    db: Optional[PacDB] = None,
    now_ts: int = 0,
) -> List[SourceFile]:
    src_root = src_root.resolve()
    results: List[SourceFile] = []

    # First, discover all flac files
    flac_paths = []
    for dirpath, _, filenames in os.walk(src_root):
        for name in filenames:
            if name.lower().endswith(".flac"):
                flac_paths.append(Path(dirpath) / name)

    if not compute_flac_md5:
        for full in flac_paths:
            try:
                st = full.stat()
                rel = full.relative_to(src_root)
                results.append(SourceFile(
                    path=full,
                    rel_path=rel,
                    size=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    flac_md5=None,
                ))
            except OSError:
                continue
        return results

    # Now, process them in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(read_flac_streaminfo_md5, path): path for path in flac_paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                md5 = future.result()
                st = path.stat()
                rel = path.relative_to(src_root)
                results.append(SourceFile(
                    path=path,
                    rel_path=rel,
                    size=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    flac_md5=md5,
                ))
            except Exception:
                # Log error or handle as needed
                continue

    if db and results:
        try:
            db.begin()
            db.upsert_many_source_files(
                [
                    (
                        str(sf.flac_md5),
                        now_ts,
                        sf.size,
                        sf.mtime_ns,
                        str(sf.rel_path),
                        now_ts,
                    )
                    for sf in results
                    if sf.flac_md5
                ]
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

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