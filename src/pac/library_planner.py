"""Planning for FLAC library maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Literal
import time

from loguru import logger

from .config import PacSettings
from .scanner import SourceFile
from .db import PacDB
from .flac_tools import flac_stream_info, needs_cd_downmix, get_flac_tag, _resolve_art_pattern


@dataclass
class LibraryPlanItem:
    """A planned action for FLAC maintenance."""
    action: Literal["test_integrity", "resample_to_cd", "recompress", "extract_art", "hold", "skip"]
    reason: str
    src_path: Path
    rel_path: Path
    flac_md5: str
    params: Dict[str, Any]


def plan_library_actions(
    sources: List[SourceFile],
    cfg: PacSettings,
    db: PacDB,
    now_ts: int
) -> List[LibraryPlanItem]:
    """Plan actions for FLAC library maintenance."""
    plan = []


    for src in sources:
        src_path = src.path
        rel_path = src.rel_path
        md5 = src.flac_md5

        # Get stream info
        info = flac_stream_info(src_path)
        if not info:
            plan.append(LibraryPlanItem(
                action="hold",
                reason="Cannot read stream info",
                src_path=src_path,
                rel_path=rel_path,
                flac_md5=md5,
                params={}
            ))
            continue

        # Phase 1: Integrity test
        plan.append(LibraryPlanItem(
            action="test_integrity",
            reason="Verify FLAC integrity",
            src_path=src_path,
            rel_path=rel_path,
            flac_md5=md5,
            params={"streaminfo": info}
        ))


        # Phase 3: Resample to CD if needed
        if cfg.flac_resample_to_cd and needs_cd_downmix(info):
            plan.append(LibraryPlanItem(
                action="resample_to_cd",
                reason=f"Downmix {info.get('bit_depth')}bit/{info.get('sample_rate')}Hz/{info.get('channels')}ch to CD",
                src_path=src_path,
                rel_path=rel_path,
                flac_md5=md5,
                params={"target_info": info}
            ))

        # Phase 4: Recompress
        current_level = None
        compression_tag = get_flac_tag(src_path, "COMPRESSION")
        if compression_tag:
            # Try to extract level from tag
            import re
            match = re.search(r'level=(\d+)', compression_tag)
            if match:
                current_level = int(match.group(1))

        # Skip if already at target level and recently verified
        skip_recompress = False
        if current_level == cfg.flac_target_compression:
            # Check if recently verified (within 90 days)
            if db:
                row = db.conn.execute("SELECT last_test_ts FROM flac_checks WHERE md5 = ?", (md5,)).fetchone()
                if row and row["last_test_ts"]:
                    grace_period = 90 * 24 * 60 * 60  # 90 days in seconds
                    if now_ts - row["last_test_ts"] < grace_period:
                        skip_recompress = True

        if not skip_recompress:
            plan.append(LibraryPlanItem(
                action="recompress",
                reason=f"Recompress from level {current_level} to {cfg.flac_target_compression}",
                src_path=src_path,
                rel_path=rel_path,
                flac_md5=md5,
                params={"target_level": cfg.flac_target_compression, "current_level": current_level}
            ))

        # Phase 5: Artwork extraction
        art_root = Path(cfg.flac_art_root).expanduser()
        art_pattern = cfg.flac_art_pattern
        try:
            extracted_path = extract_art(src_path, art_root, art_pattern, md5, db)
            if extracted_path:
                plan.append(LibraryPlanItem(
                    action="extract_art",
                    reason="Export front cover artwork",
                    src_path=src_path,
                    rel_path=rel_path,
                    flac_md5=md5,
                    params={
                        "art_root": str(art_root),
                        "art_pattern": art_pattern,
                        "extracted_path": str(extracted_path)
                    }
                ))
        except Exception as e:
            logger.debug(f"Error planning artwork extraction for {src_path}: {e}")
            plan.append(LibraryPlanItem(
                action="hold",
                reason=f"Artwork planning error: {e}",
                src_path=src_path,
                rel_path=rel_path,
                flac_md5=md5,
                params={}
            ))

    return plan


def extract_art(
    src_path: Path,
    art_root: Path,
    art_pattern: str,
    flac_md5: str,
    db: Optional[PacDB] = None
) -> Optional[Path]:
    """
    Extract front cover artwork from FLAC file to the specified art root using the pattern.

    Returns the path where artwork was extracted, or None if no artwork or extraction failed.
    Updates DB if provided.
    """
    from .metadata import _first_front_cover
    from mutagen.flac import FLAC
    import os
    from loguru import logger

    potential_art_path = None
    try:
        flac_obj = FLAC(str(src_path))
        if not flac_obj or not _first_front_cover(flac_obj):
            logger.debug(f"No embedded artwork in {src_path}")
            return None

        potential_art_path = _resolve_art_pattern(art_pattern, flac_obj, art_root)
        if not potential_art_path:
            logger.debug(f"Could not resolve art path for {src_path}")
            return None

        # Check if extraction is needed
        art_needed = False
        if db:
            row = db.conn.execute("SELECT last_export_ts, size FROM art_exports WHERE md5 = ?", (flac_md5,)).fetchone()
            if not row:
                art_needed = True
            else:
                if potential_art_path.exists():
                    current_mtime = potential_art_path.stat().st_mtime
                    if current_mtime > row["last_export_ts"]:
                        art_needed = True
                else:
                    art_needed = True
        else:
            # No DB, extract if doesn't exist
            art_needed = not potential_art_path.exists()

        if not art_needed:
            logger.debug(f"Artwork up to date for {src_path}")
            return potential_art_path

        # Extract artwork
        # Get the front cover picture data
        front_cover = _first_front_cover(flac_obj)
        if not front_cover:
            return None

        # Ensure directory exists
        potential_art_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the image data
        with open(potential_art_path, 'wb') as f:
            f.write(front_cover)

        # Update DB if provided
        if db:
            now_ts = int(time.time())
            size = len(front_cover)
            db.conn.execute(
                "INSERT OR REPLACE INTO art_exports (md5, last_export_ts, size) VALUES (?, ?, ?)",
                (flac_md5, now_ts, size)
            )
            db.conn.commit()

        logger.info(f"Extracted artwork to {potential_art_path}")
        return potential_art_path

    except Exception as e:
        logger.warning(f"Failed to extract artwork for {src_path}: {e}")
        return None