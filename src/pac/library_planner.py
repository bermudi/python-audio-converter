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
from .flac_tools import flac_stream_info, needs_cd_downmix, get_flac_tag


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

        # Phase 5: Artwork extraction (stub)
        plan.append(LibraryPlanItem(
            action="extract_art",
            reason="Extract embedded artwork",
            src_path=src_path,
            rel_path=rel_path,
            flac_md5=md5,
            params={}
        ))

    return plan