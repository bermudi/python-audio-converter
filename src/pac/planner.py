"""Planner v2 (stateless): decide actions from source scan + destination index.

Consumes the `DestIndex` (derived from filesystem + PAC_* tags) rather than a
local DB. Produces per-source actions among {convert, skip, rename, retag} and
optional prune actions for destination-only entries when requested.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Set

from .scanner import SourceFile
from .paths import sanitize_rel_path
from .dest_index import DestIndex, DestEntry


Action = Literal["convert", "skip", "rename", "retag", "prune"]


@dataclass
class PlanItem:
    action: Action
    reason: str
    # Source context (when applicable)
    src_path: Optional[Path]
    rel_path: Optional[Path]
    flac_md5: Optional[str]
    # Expected output
    output_rel: Optional[Path]
    codec: str
    encoder: str
    vbr_quality: int
    # Destination context (when applicable)
    dest_rel: Optional[Path] = None


def plan_changes(
    scanned: Iterable[SourceFile],
    dest: DestIndex,
    *,
    codec: str = "aac",
    vbr_quality: int = 5,
    opus_vbr_kbps: int = 160,
    encoder: str = "libfdk_aac",
    force_reencode: bool = False,
    allow_rename: bool = True,
    retag_existing: bool = True,
    prune_orphans: bool = False,
    no_adopt: bool = False,
    hash_streaminfo: bool = True,
) -> List[PlanItem]:
    """Create a stateless plan.

    - Skip: PAC_SRC_MD5 matches and encoder/quality match.
    - Convert: missing output, MD5 mismatch, or encoder/quality mismatch, or forced.
    - Rename: different rel_path with same PAC_SRC_MD5 and rename allowed.
    - Retag: output present at expected rel with same MD5+encoder+quality but missing PAC_* or mismatched PAC_SOURCE_REL; adopt when `no_adopt=False`.
    - Prune: destination entries with PAC_SRC_MD5 not present in sources (when requested).
    """
    plan: List[PlanItem] = []

    suffix = ".opus" if codec == "opus" else ".m4a"
    desired_quality = opus_vbr_kbps if codec == "opus" else vbr_quality

    # Build a quick set of source MD5s for prune
    src_md5s: Set[str] = set()

    for sf in scanned:
        out_rel = sanitize_rel_path(sf.rel_path, final_suffix=suffix)

        if force_reencode:
            plan.append(
                PlanItem(
                    action="convert",
                    reason="force",
                    src_path=sf.path,
                    rel_path=sf.rel_path,
                    flac_md5=sf.flac_md5,
                    output_rel=out_rel,
                    codec=codec,
                    encoder=encoder,
                    vbr_quality=desired_quality,
                )
            )
            if sf.flac_md5:
                src_md5s.add(sf.flac_md5)
            continue

        expected: Optional[DestEntry] = dest.by_rel.get(out_rel)
        md5_match: Optional[DestEntry] = None
        if sf.flac_md5:
            src_md5s.add(sf.flac_md5)
            md5_match = dest.get_preferred_by_md5(sf.flac_md5)

        # Prefer exact path match decision first
        if expected:
            is_md5_match = bool(expected.pac_src_md5 and sf.flac_md5 and expected.pac_src_md5 == sf.flac_md5)

            # Fallback for no-hash mode: assume match if output is newer than source.
            is_time_match = not hash_streaminfo and (sf.mtime_ns < expected.mtime_ns)

            if is_md5_match or is_time_match:
                # Same content (or assumed same); check encoder/quality
                if expected.pac_encoder == encoder and str(expected.pac_quality) == str(desired_quality):
                    # Consider retagging if PAC_* incomplete or source_rel differs and allowed
                    needs_retag = False
                    if retag_existing:
                        # With time-based match, we might be missing md5, so retag is good
                        if not expected.pac_version or not expected.pac_source_rel:
                            needs_retag = True
                        elif expected.pac_source_rel != str(sf.rel_path):
                            needs_retag = True

                    reason = "md5+settings match" if is_md5_match else "time+settings match"
                    action = "retag" if needs_retag and not no_adopt else "skip"
                    if needs_retag and not no_adopt:
                        reason += "; retag"

                    plan.append(
                        PlanItem(
                            action=action,
                            reason=reason,
                            src_path=sf.path,
                            rel_path=sf.rel_path,
                            flac_md5=sf.flac_md5,
                            output_rel=out_rel,
                            codec=codec,
                            encoder=encoder,
                            vbr_quality=desired_quality,
                            dest_rel=expected.rel_path,
                        )
                    )
                else:
                    plan.append(
                        PlanItem(
                            action="convert",
                            reason="encoder/quality mismatch",
                            src_path=sf.path,
                            rel_path=sf.rel_path,
                            flac_md5=sf.flac_md5,
                            output_rel=out_rel,
                            codec=codec,
                            encoder=encoder,
                            vbr_quality=desired_quality,
                            dest_rel=expected.rel_path,
                        )
                    )
            else:
                # Expected exists but content differs (or cannot be determined)
                if not expected.pac_src_md5 and not no_adopt:
                    # Adopt the file: it's at the right path but has no PAC tags.
                    plan.append(
                        PlanItem(
                            action="retag",
                            reason="adopt: missing PAC tags",
                            src_path=sf.path,
                            rel_path=sf.rel_path,
                            flac_md5=sf.flac_md5,
                            output_rel=out_rel,
                            codec=codec,
                            encoder=encoder,
                            vbr_quality=desired_quality,
                            dest_rel=expected.rel_path,
                        )
                    )
                else:
                    # Convert because MD5 mismatches, or we are not allowed to adopt.
                    reason = "MD5 mismatch" if expected.pac_src_md5 else "adopt disabled for file with no PAC"
                    plan.append(
                        PlanItem(
                            action="convert",
                            reason=reason,
                            src_path=sf.path,
                            rel_path=sf.rel_path,
                            flac_md5=sf.flac_md5,
                            output_rel=out_rel,
                            codec=codec,
                            encoder=encoder,
                            vbr_quality=desired_quality,
                            dest_rel=expected.rel_path,
                        )
                    )
            continue

        # No expected file; can we rename an existing output with the same MD5?
        if md5_match and allow_rename:
            plan.append(
                PlanItem(
                    action="rename",
                    reason="md5 match at different path",
                    src_path=sf.path,
                    rel_path=sf.rel_path,
                    flac_md5=sf.flac_md5,
                    output_rel=out_rel,
                    codec=codec,
                    encoder=encoder,
                    vbr_quality=desired_quality,
                    dest_rel=md5_match.rel_path,
                )
            )
            continue

        # Adopt: output present at expected path but lacking PAC_* (covered earlier). If no expected, we convert.
        # Default path: need to encode
        plan.append(
            PlanItem(
                action="convert",
                reason="no output",
                src_path=sf.path,
                rel_path=sf.rel_path,
                flac_md5=sf.flac_md5,
                output_rel=out_rel,
                codec=codec,
                encoder=encoder,
                vbr_quality=desired_quality,
            )
        )

    # Optional prune: destination entries whose PAC_SRC_MD5 not present in sources
    if prune_orphans:
        for entry in dest.all_entries():
            md5 = entry.pac_src_md5
            if not md5:
                continue  # don't prune unknown provenance automatically
            if md5 not in src_md5s:
                plan.append(
                    PlanItem(
                        action="prune",
                        reason="orphan: no matching source MD5",
                        src_path=None,
                        rel_path=None,
                        flac_md5=md5,
                        output_rel=None,
                        codec=entry.container,
                        encoder="",
                        vbr_quality=0,
                        dest_rel=entry.rel_path,
                    )
                )

    return plan
