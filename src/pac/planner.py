"""Planner: decide what needs conversion based on scan vs DB.

Considers file attributes and encoder settings so we only re-encode when needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Literal, Optional

from .scanner import SourceFile


Decision = Literal["convert", "skip"]


@dataclass
class PlanItem:
    decision: Decision
    reason: str
    src_path: Path
    rel_path: Path
    output_rel: Path
    vbr_quality: int = 5
    encoder: str = "libfdk_aac"
    size: int | None = None
    mtime_ns: int | None = None
    flac_md5: str | None = None


def plan_changes(
    scanned: Iterable[SourceFile],
    db_index: dict[str, "sqlite3.Row"],
    *,
    vbr_quality: int = 5,
    encoder: str = "libfdk_aac",
    force: bool = False,
) -> List[PlanItem]:
    import sqlite3  # local import to avoid hard dependency at import time

    plan: List[PlanItem] = []
    for sf in scanned:
        prev = db_index.get(str(sf.path))
        out_rel = sf.rel_path.with_suffix(".m4a")
        reason = ""
        if force:
            decision: Decision = "convert"
            reason = "force"
        else:
            if prev is None:
                decision = "convert"
                reason = "not in DB"
            else:
                reasons: list[str] = []
                if prev["size"] != sf.size:
                    reasons.append("size")
                if prev["mtime_ns"] != sf.mtime_ns:
                    reasons.append("mtime")
                if prev["flac_md5"] and sf.flac_md5 and prev["flac_md5"] != sf.flac_md5:
                    reasons.append("md5")
                if prev["vbr_quality"] != vbr_quality:
                    reasons.append("quality")
                if prev["encoder"] != encoder:
                    reasons.append("encoder")

                if reasons:
                    decision = "convert"
                    reason = "changed: " + ", ".join(reasons)
                else:
                    decision = "skip"
                    reason = "unchanged"
        plan.append(PlanItem(
            decision=decision,
            reason=reason,
            src_path=sf.path,
            rel_path=sf.rel_path,
            output_rel=out_rel,
            vbr_quality=vbr_quality,
            encoder=encoder,
            size=sf.size,
            mtime_ns=sf.mtime_ns,
            flac_md5=sf.flac_md5,
        ))
    return plan
