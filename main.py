from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import time
import threading
from typing import Any, Optional, Callable

from loguru import logger

# Ensure local src/ is importable when running from project root
ROOT = Path(__file__).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Prefer line-buffered output so progress prints appear promptly under wrappers
try:  # Python 3.7+
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

from pac.ffmpeg_check import probe_ffmpeg, probe_fdkaac, probe_qaac  # noqa: E402
from pac.encoder import (  # noqa: E402
    encode_with_ffmpeg_libfdk,
    run_ffmpeg_pipe_to_qaac,
    run_ffmpeg_pipe_to_fdkaac,
    encode_with_ffmpeg_libopus,
)
from pac.metadata import (  # noqa: E402
    copy_tags_flac_to_mp4,
    verify_tags_flac_vs_mp4,
    copy_tags_flac_to_opus,
    verify_tags_flac_vs_opus,
    write_pac_tags_mp4,
    write_pac_tags_opus,
)
from pac.scanner import scan_flac_files  # noqa: E402
from pac.scheduler import WorkerPool  # noqa: E402
from pac.planner import plan_changes  # noqa: E402
from pac.config import PacSettings, cli_overrides_from_args  # noqa: E402
from pac.paths import resolve_collisions, sanitize_rel_path  # noqa: E402
from pac.dest_index import build_dest_index  # noqa: E402


EXIT_OK = 0
EXIT_WITH_FILE_ERRORS = 2
EXIT_PREFLIGHT_FAILED = 3

def _empty_summary() -> dict[str, Any]:
    return {
        "planned": 0,
        "to_convert": 0,
        "skipped": 0,
        "renamed": 0,
        "retagged": 0,
        "pruned": 0,
        "synced_tags": 0,
        "converted": 0,
        "failed": 0,
    }


def configure_logging(log_level: str = "INFO", log_json_path: Optional[str] = None) -> None:
    """Configure Loguru for human console output and optional JSON lines file.

    log_level: Console log level (e.g., INFO, DEBUG, WARNING).
    log_json_path: If provided, write structured JSON lines to this path.
    """
    logger.remove()
    # Human console sink
    logger.add(sys.stderr, level=log_level.upper(), enqueue=True, backtrace=False, diagnose=False)
    # Optional JSON lines sink
    if log_json_path:
        logger.add(log_json_path, level="DEBUG", serialize=True, enqueue=True)


def cmd_preflight() -> int:
    st = probe_ffmpeg()
    if not st.available:
        logger.error("ffmpeg: NOT FOUND")
        if st.error:
            logger.error(st.error)
        return EXIT_PREFLIGHT_FAILED
    logger.info(f"ffmpeg: {st.ffmpeg_path}")
    logger.info(f"version: {st.ffmpeg_version}")
    logger.info(f"libfdk_aac (ffmpeg): {'YES' if st.has_libfdk_aac else 'NO'}")

    st_fdk = probe_fdkaac()
    logger.info(f"fdkaac: {'FOUND' if st_fdk.available else 'NOT FOUND'}")
    if st_fdk.available:
        logger.info(f"fdkaac path: {st_fdk.fdkaac_path}")
        if st_fdk.fdkaac_version:
            logger.info(st_fdk.fdkaac_version)

    st_qaac = probe_qaac(light=False)
    logger.info(f"qaac: {'FOUND' if st_qaac.available else 'NOT FOUND'}")
    if st_qaac.available:
        logger.info(f"qaac path: {st_qaac.qaac_path}")
        if st_qaac.qaac_version:
            logger.info(st_qaac.qaac_version)

    ok = st.available and (st.has_libfdk_aac or st_fdk.available or st_qaac.available)
    if not ok:
        logger.error("No AAC encoder available. Install ffmpeg with libfdk_aac, or fdkaac, or qaac.")
    return EXIT_OK if ok else EXIT_PREFLIGHT_FAILED


def cmd_convert(
    src: str,
    dest: str,
    tvbr: int,
    vbr: int,
    *,
    pcm_codec: str,
    verify_tags: bool,
    verify_strict: bool,
    log_json_path: Optional[str],
) -> int:
    src_p = Path(src)
    dest_p = Path(dest)

    st = probe_ffmpeg()
    if not st.available:
        logger.error("ffmpeg not found; cannot convert")
        return EXIT_PREFLIGHT_FAILED

    rc = 1
    if st.has_libfdk_aac:
        rc = encode_with_ffmpeg_libfdk(src_p, dest_p, vbr_quality=vbr)
    else:
        st_qaac = probe_qaac()
        if st_qaac.available:
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr, pcm_codec=pcm_codec)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=vbr, pcm_codec=pcm_codec)
            else:
                logger.error("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                return EXIT_PREFLIGHT_FAILED

    if rc != 0:
        logger.error(f"Encode failed with exit code {rc}")
        return EXIT_WITH_FILE_ERRORS

    # Best-effort tag copy from FLAC -> MP4
    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Metadata copy failed: {e}")

    # Embed PAC_* tags
    try:
        enc = "libfdk_aac" if st.has_libfdk_aac else ("qaac" if probe_qaac().available else ("fdkaac" if probe_fdkaac().available else "aac"))
        qual = str(tvbr) if enc == "qaac" else str(vbr)
        write_pac_tags_mp4(
            dest_p,
            src_md5="",  # unknown here unless we rescan; planner can rely on later flows
            encoder=enc,
            quality=qual,
            version="0.2",
            source_rel=src_p.name,
        )
    except Exception as e:
        logger.bind(action="pac_tags", file=str(src_p.name), status="warn", reason=str(e)).warning("PAC_* embed failed")

    # Optional verification
    if verify_tags:
        try:
            disc = verify_tags_flac_vs_mp4(src_p, dest_p)
        except Exception as e:
            disc = [f"verify-exception: {e}"]
        status = "ok" if not disc else ("failed" if verify_strict else "warn")
        logger.bind(action="verify", file=str(src_p.name), status=status, discrepancies=disc).log("WARNING" if disc else "INFO", "verify complete")
        if disc and verify_strict:
            return EXIT_WITH_FILE_ERRORS
    logger.info(f"Wrote: {dest_p}")
    return EXIT_OK


def _encode_one_selected(
    src_p: Path,
    dest_p: Path,
    *,
    codec: str,
    encoder: str,
    tvbr: int,
    vbr: int,
    opus_vbr_kbps: int,
    pcm_codec: str,
    verify_tags: bool,
    verify_strict: bool,
    cover_art_resize: bool,
    cover_art_max_size: int,
) -> tuple[int, str]:
    """Encode using the preselected backend to keep DB planning consistent."""
    if codec == "opus":
        rc = encode_with_ffmpeg_libopus(src_p, dest_p, vbr_kbps=opus_vbr_kbps)
        if rc != 0:
            return rc, "failed"
    elif encoder == "libfdk_aac":
        rc = encode_with_ffmpeg_libfdk(src_p, dest_p, vbr_quality=vbr)
        if rc != 0:
            return rc, "failed"
    elif encoder == "qaac":
        rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr, pcm_codec=pcm_codec)
        if rc != 0:
            return rc, "failed"
    elif encoder == "fdkaac":
        rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=vbr, pcm_codec=pcm_codec)
        if rc != 0:
            return rc, "failed"
    else:  # pragma: no cover - defensive
        logger.error(f"Unknown encoder combination: codec={codec}, encoder={encoder}")
        return 1, "failed"

    # Metadata copy and verification
    try:
        if codec == "opus":
            copy_tags_flac_to_opus(
                src_p, dest_p, cover_art_resize=cover_art_resize, cover_art_max_size=cover_art_max_size
            )
        else:
            copy_tags_flac_to_mp4(
                src_p, dest_p, cover_art_resize=cover_art_resize, cover_art_max_size=cover_art_max_size
            )
        logger.bind(action="tags", file=str(src_p.name), status="ok").info("tags copy ok")
    except Exception as e:
        reason = f"copy-exception: {e}"
        logger.bind(action="tags", file=str(src_p.name), status="error", reason=reason).error("tags copy failed")
        if verify_strict:
            return 1, "failed"
        return 0, "warn"

    # Embed PAC_* tags
    try:
        if codec == "opus":
            write_pac_tags_opus(
                dest_p,
                src_md5="",
                encoder="libopus",
                quality=str(opus_vbr_kbps),
                version="0.2",
                source_rel=src_p.name,
            )
        else:
            write_pac_tags_mp4(
                dest_p,
                src_md5="",
                encoder=encoder,
                quality=str(tvbr if encoder == "qaac" else vbr),
                version="0.2",
                source_rel=src_p.name,
            )
    except Exception as e:
        logger.bind(action="pac_tags", file=str(src_p.name), status="warn", reason=str(e)).warning("PAC_* embed failed")

    ver_status = "skipped"
    if verify_tags:
        try:
            if codec == "opus":
                disc = verify_tags_flac_vs_opus(src_p, dest_p)
            else:
                disc = verify_tags_flac_vs_mp4(src_p, dest_p)
        except Exception as e:
            disc = [f"verify-exception: {e}"]
        ver_status = "ok" if not disc else ("failed" if verify_strict else "warn")
        level = "INFO"
        if ver_status == "failed":
            level = "ERROR"
        elif ver_status == "warn":
            level = "WARNING"
        logger.bind(action="verify", file=str(src_p), status=ver_status, discrepancies=disc).log(level, "verify complete")
        if disc and verify_strict:
            return 1, "failed"
    return 0, ver_status


def _encode_one_selected_timed(
    src_p: Path,
    dest_p: Path,
    *,
    codec: str,
    encoder: str,
    tvbr: int,
    vbr: int,
    opus_vbr_kbps: int,
    pcm_codec: str,
    verify_tags: bool,
    verify_strict: bool,
    cover_art_resize: bool,
    cover_art_max_size: int,
) -> tuple[int, float, str]:
    """Wrapper that measures wall time for a single encode."""
    t0 = time.time()
    rc, ver_status = _encode_one_selected(
        src_p,
        dest_p,
        codec=codec,
        encoder=encoder,
        tvbr=tvbr,
        vbr=vbr,
        opus_vbr_kbps=opus_vbr_kbps,
        pcm_codec=pcm_codec,
        verify_tags=verify_tags,
        verify_strict=verify_strict,
        cover_art_resize=cover_art_resize,
        cover_art_max_size=cover_art_max_size,
    )
    return rc, time.time() - t0, ver_status


def cmd_convert_dir(
    src_dir: str,
    out_dir: str,
    *,
    codec: str,
    tvbr: int,
    vbr: int,
    opus_vbr_kbps: int,
    workers: int | None,
    
    verbose: bool,
    dry_run: bool,
    force_reencode: bool,
    allow_rename: bool,
    retag_existing: bool,
    prune_orphans: bool,
    no_adopt: bool,
    sync_tags: bool = False,
    log_json_path: Optional[str] = None,
    pcm_codec: str = "pcm_s24le",
    verify_tags: bool = False,
    verify_strict: bool = False,
    cover_art_resize: bool = True,
    cover_art_max_size: int = 1500,
    stop_event: Optional[threading.Event] = None,
    pause_event: Optional[threading.Event] = None,
) -> tuple[int, dict[str, Any]]:
    src_root = Path(src_dir).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Preflight: detect ffmpeg and choose encoder once for the whole run (stable planning)
    t_preflight_s = time.time()
    t_probe_ff = time.time(); st = probe_ffmpeg(); d_probe_ff = time.time() - t_probe_ff
    selected_encoder = None
    st_qaac = None
    st_fdk = None
    if not st.available:
        logger.error("ffmpeg not found; cannot convert")
        return EXIT_PREFLIGHT_FAILED, _empty_summary()

    if codec == "opus":
        if st.has_libopus:
            selected_encoder = "libopus"
        else:
            logger.error("Opus encoding requested, but libopus not found in ffmpeg")
            return EXIT_PREFLIGHT_FAILED, _empty_summary()
    else:  # aac
        if st.has_libfdk_aac:
            selected_encoder = "libfdk_aac"
        else:
            t_probe_qa = time.time(); st_qaac = probe_qaac(); d_probe_qa = time.time() - t_probe_qa
            if st_qaac.available:
                selected_encoder = "qaac"
            else:
                t_probe_fd = time.time(); st_fdk = probe_fdkaac(); d_probe_fd = time.time() - t_probe_fd
                if st_fdk.available:
                    selected_encoder = "fdkaac"
                else:
                    logger.error("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                    return EXIT_PREFLIGHT_FAILED, _empty_summary()

    d_preflight = time.time() - t_preflight_s
    quality_for_run = opus_vbr_kbps if codec == "opus" else (tvbr if selected_encoder == "qaac" else vbr)

    # Scan
    max_workers = workers or (os.cpu_count() or 1)
    t_scan_s = time.time()
    files = scan_flac_files(src_root, compute_flac_md5=True, max_workers=max_workers)
    d_scan = time.time() - t_scan_s
    if not files:
        logger.info("No .flac files found")
        return EXIT_OK, _empty_summary()

    # Destination index and plan (stateless)
    t_idx_s = time.time()
    dest_index = build_dest_index(out_root, max_workers=max_workers)
    d_db = time.time() - t_idx_s
    t_plan_s = time.time()
    plan = plan_changes(
        files,
        dest_index,
        codec=codec,
        vbr_quality=tvbr if selected_encoder == "qaac" else vbr,
        opus_vbr_kbps=opus_vbr_kbps,
        encoder=selected_encoder,
        force_reencode=force_reencode,
        allow_rename=allow_rename,
        retag_existing=retag_existing,
        prune_orphans=prune_orphans,
        no_adopt=no_adopt,
        sync_tags=sync_tags,
        out_root=out_root,
    )
    d_plan = time.time() - t_plan_s

    to_convert = [pi for pi in plan if pi.action == "convert"]
    unchanged = [pi for pi in plan if pi.action == "skip"]
    to_rename = [pi for pi in plan if pi.action == "rename"]
    to_retag = [pi for pi in plan if pi.action == "retag"]
    to_prune = [pi for pi in plan if pi.action == "prune"]
    to_sync_tags = [pi for pi in plan if pi.action == "sync_tags"]

    # Always provide basic run info
    quality_str = opus_vbr_kbps if codec == "opus" else (tvbr if selected_encoder == "qaac" else vbr)
    logger.info(
        f"Codec: {codec} | Selected encoder: {selected_encoder} | Quality: {quality_str}"
        f" | PCM: {pcm_codec} | Workers: {max_workers}"
        f" | Force: {'on' if force_reencode else 'off'} | Rename: {'on' if allow_rename else 'off'} | Retag: {'on' if retag_existing else 'off'} | Prune: {'on' if prune_orphans else 'off'} | Adopt: {'off' if no_adopt else 'on'}"
    )
    # Show encoder binary path for transparency
    if selected_encoder == "libfdk_aac":
        logger.info(f"Encoder path: ffmpeg -> {st.ffmpeg_path}")
    elif selected_encoder == "qaac" and st_qaac is not None and getattr(st_qaac, 'qaac_path', None):
        logger.info(f"Encoder path: qaac -> {st_qaac.qaac_path}")
    elif selected_encoder == "fdkaac" and st_fdk is not None and getattr(st_fdk, 'fdkaac_path', None):
        logger.info(f"Encoder path: fdkaac -> {st_fdk.fdkaac_path}")
    logger.info(f"Source: {src_root} -> Dest: {out_root}")
    logger.info(
        f"Planned: {len(plan)} | Convert: {len(to_convert)} | Skip: {len(unchanged)} | Rename: {len(to_rename)} | Retag: {len(to_retag)} | Prune: {len(to_prune)} | Sync Tags: {len(to_sync_tags)}"
    )

    # Concise plan breakdown by change reason
    if plan and force_reencode:
        logger.info(f"Plan breakdown: forced={len(to_convert)}")

    # Stateless run: record summary only at the end

    # Dry-run: show planned actions and exit without encoding
    if dry_run:
        logger.info("Plan details:")
        for pi in plan:
            if pi.action == "convert":
                logger.info(f"CONVERT  {pi.rel_path} -> {pi.output_rel} | {pi.reason}")
            elif pi.action == "rename":
                logger.info(f"RENAME   {pi.dest_rel} -> {pi.output_rel} | {pi.reason}")
            elif pi.action == "retag":
                logger.info(f"RETAG    {pi.output_rel} | {pi.reason}")
            elif pi.action == "prune":
                logger.info(f"PRUNE    {pi.dest_rel} | {pi.reason}")
            elif pi.action == "sync_tags":
                logger.info(f"SYNC TAGS {pi.output_rel} | {pi.reason}")
            else:
                logger.info(f"SKIP     {pi.rel_path} | {pi.reason}")
        plan_summary = {
            "planned": len(plan),
            "to_convert": len(to_convert),
            "skipped": len(unchanged),
            "renamed": len(to_rename),
            "retagged": len(to_retag),
            "pruned": len(to_prune),
            "to_sync_tags": len(to_sync_tags),
            "converted": 0,
            "failed": 0,
        }
        return EXIT_OK, plan_summary

    if verbose:
        logger.debug(
            "Preflight: ffmpeg probe = "
            + f"{d_probe_ff:.3f}s"
            + (f", qaac probe = {d_probe_qa:.3f}s" if 'd_probe_qa' in locals() else "")
            + (f", fdkaac probe = {d_probe_fd:.3f}s" if 'd_probe_fd' in locals() else "")
        )
        logger.debug(f"Scan: {len(files)} files in {d_scan:.3f}s | Index: {d_db:.3f}s | Plan: {d_plan:.3f}s")

    pool = WorkerPool(max_workers=max_workers)

    converted = 0
    failed = 0
    renamed = 0
    retagged = 0
    pruned = 0
    synced_tags = 0

    t_encode_s = time.time()
    # Verification counters
    ver_checked = 0
    ver_ok = 0
    ver_warn = 0
    ver_failed = 0

    # Collect results as they complete and update DB for successes
    total_bytes = 0
    done = 0
    since_commit = 0  # retained for structure; no DB commits in stateless

    # Optional: sync-tags mode processes unchanged items with tag copy + verify
    tag_sync_processed = 0
    tag_sync_ok = 0
    tag_sync_warn = 0
    tag_sync_failed = 0

    if prune_orphans and to_prune and not dry_run:
        try:
            prompt = f"Prune will delete {len(to_prune)} files from the destination. This cannot be undone. Continue? [y/N]: "
            resp = input(prompt)
            if str(resp).strip().lower() not in {"y", "yes"}:
                logger.warning("Prune cancelled by user")
                to_prune = []  # Empty the list so no pruning happens
        except Exception:
            logger.warning("Could not get confirmation; cancelling prune.")
            to_prune = []

    if force_reencode and not dry_run:
        try:
            prompt = f"Force re-encode will process {len(to_convert)} files. Continue? [y/N]: "
            resp = input(prompt)
            if str(resp).strip().lower() not in {"y", "yes"}:
                logger.warning("Force re-encode cancelled by user")
                return EXIT_OK, _empty_summary()
        except Exception:
            pass

    # Execute filesystem actions first (rename, retag, prune)
    for pi in to_rename:
        try:
            src_p = out_root / (pi.dest_rel or Path(""))
            dst_p = out_root / (pi.output_rel or Path(""))
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            src_p.replace(dst_p)
            renamed += 1
            logger.info(f"RENAME OK  {pi.dest_rel} -> {pi.output_rel}")
        except Exception as e:
            failed += 1
            logger.error(f"RENAME ERR {pi.dest_rel} -> {pi.output_rel}: {e}")

    for pi in to_retag:
        try:
            dp = out_root / (pi.output_rel or Path(""))
            if codec == "opus" or (dp.suffix.lower() == ".opus"):
                write_pac_tags_opus(
                    dp,
                    src_md5=str(pi.flac_md5 or ""),
                    encoder="libopus" if codec == "opus" else str(pi.encoder),
                    quality=str(pi.vbr_quality),
                    version="0.2",
                    source_rel=str(pi.rel_path or ""),
                )
            else:
                write_pac_tags_mp4(
                    dp,
                    src_md5=str(pi.flac_md5 or ""),
                    encoder=str(pi.encoder),
                    quality=str(pi.vbr_quality),
                    version="0.2",
                    source_rel=str(pi.rel_path or ""),
                )
            retagged += 1
            logger.info(f"RETAG  OK  {pi.output_rel}")
        except Exception as e:
            failed += 1
            logger.error(f"RETAG  ERR {pi.output_rel}: {e}")

    for pi in to_prune:
        try:
            dp = out_root / (pi.dest_rel or Path(""))
            dp.unlink(missing_ok=True)
            pruned += 1
            logger.info(f"PRUNE  OK  {pi.dest_rel}")
        except Exception as e:
            failed += 1
            logger.error(f"PRUNE  ERR {pi.dest_rel}: {e}")

    for pi in to_sync_tags:
        try:
            dp = out_root / (pi.output_rel or Path(""))
            if codec == "opus" or (dp.suffix.lower() == ".opus"):
                copy_tags_flac_to_opus(
                    pi.src_path,
                    dp,
                    cover_art_resize=cover_art_resize,
                    cover_art_max_size=cover_art_max_size,
                )
            else:
                copy_tags_flac_to_mp4(
                    pi.src_path,
                    dp,
                    cover_art_resize=cover_art_resize,
                    cover_art_max_size=cover_art_max_size,
                )
            synced_tags += 1
            logger.info(f"SYNC TAGS OK  {pi.output_rel}")
        except Exception as e:
            failed += 1
            logger.error(f"SYNC TAGS ERR {pi.output_rel}: {e}")
    # Bounded processing via WorkerPool to keep <= ~2x workers in flight
    bound = max(1, max_workers * 2)

    def _task(pi):
        dp = out_root / pi.output_rel
        dp.parent.mkdir(parents=True, exist_ok=True)
        return _encode_one_selected_timed(
            pi.src_path,
            dp,
            codec=codec,
            encoder=selected_encoder,
            tvbr=tvbr,
            vbr=vbr,
            opus_vbr_kbps=opus_vbr_kbps,
            pcm_codec=pcm_codec,
            verify_tags=verify_tags,
            verify_strict=verify_strict,
            cover_art_resize=cover_art_resize,
            cover_art_max_size=cover_art_max_size,
        )

    for pi, res in pool.imap_unordered_bounded(
        _task, to_convert, max_pending=bound, stop_event=stop_event, pause_event=pause_event
    ):
        dest_path = out_root / pi.output_rel
        rc, elapsed_s, ver_status = res
        done += 1
        if rc == 0:
            converted += 1
            if verify_tags:
                ver_checked += 1
                if ver_status == "ok":
                    ver_ok += 1
                elif ver_status == "warn":
                    ver_warn += 1
                elif ver_status == "failed":
                    ver_failed += 1
            # Embed PAC_* tags into outputs to support stateless planning
            try:
                if codec == "opus":
                    write_pac_tags_opus(
                        dest_path,
                        src_md5=str(getattr(pi, "flac_md5", "") or ""),
                        encoder=str(getattr(pi, "encoder", "")) or "libopus",
                        quality=str(getattr(pi, "vbr_quality", "") or opus_vbr_kbps),
                        version="0.2",
                        source_rel=str(getattr(pi, "rel_path", "")),
                    )
                else:
                    write_pac_tags_mp4(
                        dest_path,
                        src_md5=str(getattr(pi, "flac_md5", "") or ""),
                        encoder=str(getattr(pi, "encoder", "")) or ("qaac" if "qaac" in str(getattr(pi, "encoder", "")) else "libfdk_aac"),
                        quality=str(getattr(pi, "vbr_quality", "")),
                        version="0.2",
                        source_rel=str(getattr(pi, "rel_path", "")),
                    )
            except Exception as e:
                logger.bind(action="pac_tags", file=str(pi.rel_path), status="warn", reason=str(e)).warning("PAC_* embed failed")
            # no DB ops in stateless mode
            try:
                sz = dest_path.stat().st_size
                total_bytes += sz
            except Exception:
                pass
            logger.bind(action="encode", file=str(pi.rel_path), status="ok", elapsed_ms=int(elapsed_s*1000), bytes_out=int(sz) if 'sz' in locals() else None).info("encode complete")
            logger.info(f"[{done}/{len(to_convert)}] OK  {pi.rel_path} -> {pi.output_rel}")
        else:
            failed += 1
            logger.bind(action="encode", file=str(pi.rel_path), status="error", elapsed_ms=int(elapsed_s*1000)).error("encode failed")
            logger.error(f"[{done}/{len(to_convert)}] ERR {pi.rel_path} -> {pi.output_rel}")
            # no DB ops in stateless mode

    pool.shutdown()
    d_encode = time.time() - t_encode_s

    total = len(plan)
    logger.info(
        f"Planned: {total} | Convert: {len(to_convert)} | Skip: {len(unchanged)} | Rename: {renamed} | Retag: {retagged} | Prune: {pruned} | Synced Tags: {synced_tags} | Converted: {converted} | Failed: {failed}"
    )
    # Always print concise timing summary
    d_total = time.time() - t_preflight_s
    logger.info(
        f"Timing: total={d_total:.3f}s preflight={d_preflight:.3f}s scan={d_scan:.3f}s index={d_db:.3f}s plan={d_plan:.3f}s encode={d_encode:.3f}s"
    )
    if converted:
        thr = converted / d_encode if d_encode > 0 else float('inf')
        logger.info(f"Throughput: {converted} files in {d_encode:.2f}s = {thr:.2f} files/s | Output size: {total_bytes/1_000_000:.2f} MB")

    # Write run summary JSON
    summary: dict[str, Any] = {
        "source": str(src_root),
        "dest": str(out_root),
        "codec": codec,
        "encoder": selected_encoder,
        "quality": quality_for_run,
        "workers": max_workers,
        "hash": True,
        "force_reencode": bool(force_reencode),
        "counts": {
            "planned": total,
            "to_convert": len(to_convert),
            "skipped": len(unchanged),
            "renamed": renamed,
            "retagged": retagged,
            "pruned": pruned,
            "synced_tags": synced_tags,
            "converted": converted,
            "failed": failed,
        },
        "pcm_codec": pcm_codec,
        "verification": {
            "enabled": bool(verify_tags),
            "strict": bool(verify_strict),
            "checked": int(ver_checked),
            "ok": int(ver_ok),
            "warn": int(ver_warn),
            "failed": int(ver_failed),
        },
        "timing_s": {
            "total": round(d_total, 3),
            "preflight": round(d_preflight, 3),
            "scan": round(d_scan, 3),
            "index": round(d_db, 3),
            "plan": round(d_plan, 3),
            "encode": round(d_encode, 3),
        },
        "output_bytes": int(total_bytes),
        "timestamp": int(time.time()),
    }
    try:
        if log_json_path:
            summary_path = Path(str(log_json_path) + ".summary.json")
        else:
            summary_path = out_root / f"pac-run-summary-{int(time.time())}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.debug(f"Run summary written: {summary_path}")
    except Exception as e:
        logger.warning(f"Failed to write run summary JSON: {e}")
    return EXIT_OK if failed == 0 else EXIT_WITH_FILE_ERRORS, summary["counts"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python-audio-converter")
    # Config/Logging options (defaults resolved via PacSettings)
    p.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to TOML config (default: ~/.config/python-audio-converter/config.toml)",
    )
    p.add_argument(
        "--write-config",
        action="store_true",
        help="Write current effective settings to the config file and exit",
    )
    p.add_argument(
        "--log-level",
        default=None,
        help="Console log level (DEBUG, INFO, WARNING, ERROR)",
    )
    p.add_argument(
        "--log-json",
        dest="log_json",
        default=None,
        help="Path to write JSON lines log (structured events)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="Check ffmpeg and AAC encoder availability")

    p_convert = sub.add_parser(
        "convert",
        help="Convert a single source file to M4A (tvbr by default)",
    )
    p_convert.add_argument("src", help="Input audio file (e.g., FLAC)")
    p_convert.add_argument("dest", help="Output .m4a path")
    p_convert.add_argument(
        "--tvbr",
        type=int,
        default=None,
        help="qaac true VBR value targeting around 256 kbps (default from settings)",
    )
    p_convert.add_argument(
        "--vbr",
        type=int,
        default=None,
        help="libfdk_aac/fdkaac VBR quality/mode 1..5 (default from settings)",
    )
    p_convert.add_argument(
        "--pcm-codec",
        dest="pcm_codec",
        choices=["pcm_s24le", "pcm_f32le", "pcm_s16le"],
        default=None,
        help="PCM codec for ffmpeg decode when piping (default from settings)",
    )
    p_convert.add_argument(
        "--verify-tags",
        action="store_true",
        help="After tag copy, verify a subset of tags persisted to the MP4",
    )
    p_convert.add_argument(
        "--verify-strict",
        action="store_true",
        help="Treat any tag verification discrepancy as a failure",
    )

    p_dir = sub.add_subparser if False else sub.add_parser(  # keep structure simple
        "convert-dir",
        help="Batch convert a source directory of .flac files to a destination tree",
    )
    p_dir.add_argument("--in", dest="in_dir", required=True, help="Source directory containing .flac files")
    p_dir.add_argument("--out", dest="out_dir", required=True, help="Destination root directory for .m4a outputs")
    p_dir.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers (default from settings: CPU cores if unset)",
    )
    p_dir.add_argument(
        "--codec",
        choices=["aac", "opus"],
        default=None,
        help="Output codec (default from settings: aac)",
    )
    p_dir.add_argument(
        "--tvbr",
        type=int,
        default=None,
        help="qaac true VBR value targeting around 256 kbps (default from settings)",
    )
    p_dir.add_argument(
        "--vbr",
        type=int,
        default=None,
        help="libfdk_aac/fdkaac VBR quality/mode 1..5 (default from settings)",
    )
    p_dir.add_argument(
        "--opus-vbr-kbps",
        type=int,
        default=None,
        help="Opus VBR bitrate in kbps (default from settings)",
    )
    p_dir.add_argument(
        "--pcm-codec",
        dest="pcm_codec",
        choices=["pcm_s24le", "pcm_f32le", "pcm_s16le"],
        default=None,
        help="PCM codec for ffmpeg decode when piping (default from settings)",
    )
    
    p_dir.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging: probe details, per-phase timing, per-file results",
    )
    p_dir.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan (convert/skip/reasons) and exit without encoding",
    )
    # Stateless planner flags
    p_dir.add_argument(
        "--force-reencode",
        action="store_true",
        help="Force re-encode all sources regardless of existing outputs",
    )
    rename_group = p_dir.add_mutually_exclusive_group()
    rename_group.add_argument("--rename", dest="allow_rename", action="store_const", const=True, default=True, help="Allow planner to rename existing outputs to new paths")
    rename_group.add_argument("--no-rename", dest="allow_rename", action="store_const", const=False, help="Disallow rename actions")
    retag_group = p_dir.add_mutually_exclusive_group()
    retag_group.add_argument("--retag-existing", dest="retag_existing", action="store_const", const=True, default=True, help="Retag existing outputs with missing/old PAC_* tags")
    retag_group.add_argument("--no-retag-existing", dest="retag_existing", action="store_const", const=False, help="Do not retag existing outputs")
    p_dir.add_argument("--prune", dest="prune_orphans", action="store_true", help="Delete destination files whose PAC_SRC_MD5 no longer exists in sources")
    p_dir.add_argument("--no-adopt", dest="no_adopt", action="store_true", help="Do not adopt/retag outputs missing PAC_* tags even if content matches")
    p_dir.add_argument("--sync-tags", dest="sync_tags", action="store_true", help="Sync tags for files with matching audio content but different metadata")
    p_dir.add_argument(
        "--verify-tags",
        action="store_true",
        help="After tag copy, verify a subset of tags persisted to the MP4",
    )
    p_dir.add_argument(
        "--verify-strict",
        action="store_true",
        help="Treat any tag verification discrepancy as a failure",
    )

    # Cover art options
    cover_art_group = p_dir.add_mutually_exclusive_group()
    cover_art_group.add_argument(
        "--cover-art-resize",
        dest="cover_art_resize",
        action="store_const",
        const=True,
        default=None,
        help="Enable resizing of cover art images that exceed max dimensions",
    )
    cover_art_group.add_argument(
        "--no-cover-art-resize",
        dest="cover_art_resize",
        action="store_const",
        const=False,
        help="Disable resizing of cover art images",
    )
    p_dir.add_argument(
        "--cover-art-max-size",
        type=int,
        default=None,
        help="Max dimension (width or height) for cover art (default from settings)",
    )

    args = p.parse_args(argv)
    # Load settings: defaults + TOML + env + CLI overrides
    overrides = cli_overrides_from_args(args)
    cfg = PacSettings.load(config_path=Path(args.config_path).expanduser() if args.config_path else None, overrides=overrides)

    # Write config and exit if requested
    if args.write_config:
        written = cfg.write(Path(args.config_path).expanduser() if args.config_path else None)
        print(f"Config written to: {written}")
        return EXIT_OK

    # Configure logging using effective settings
    configure_logging(cfg.log_level, cfg.log_json)
    if args.cmd == "preflight":
        return cmd_preflight()
    if args.cmd == "convert":
        tvbr_eff = args.tvbr if args.tvbr is not None else cfg.tvbr
        vbr_eff = args.vbr if args.vbr is not None else cfg.vbr
        pcm_eff = args.pcm_codec if getattr(args, "pcm_codec", None) is not None else cfg.pcm_codec
        ver_tags_eff = bool(args.verify_tags) or bool(cfg.verify_tags)
        ver_strict_eff = bool(args.verify_strict) or bool(cfg.verify_strict)
        return cmd_convert(
            args.src,
            args.dest,
            tvbr_eff,
            vbr_eff,
            pcm_codec=pcm_eff,
            verify_tags=ver_tags_eff,
            verify_strict=ver_strict_eff,
            log_json_path=cfg.log_json,
        )
    if args.cmd == "convert-dir":
        codec_eff = args.codec if args.codec is not None else cfg.codec
        tvbr_eff = args.tvbr if args.tvbr is not None else cfg.tvbr
        vbr_eff = args.vbr if args.vbr is not None else cfg.vbr
        opus_vbr_kbps_eff = args.opus_vbr_kbps if args.opus_vbr_kbps is not None else cfg.opus_vbr_kbps
        workers_eff = args.workers if args.workers is not None else (cfg.workers or (os.cpu_count() or 1))
        
        pcm_eff = args.pcm_codec if getattr(args, "pcm_codec", None) is not None else cfg.pcm_codec
        ver_tags_eff = bool(args.verify_tags) or bool(cfg.verify_tags)
        ver_strict_eff = bool(args.verify_strict) or bool(cfg.verify_strict)
        # Stateless planner flags (no config defaults yet; rely on CLI defaults)
        force_reencode_eff = bool(getattr(args, "force_reencode", False))
        allow_rename_eff = bool(getattr(args, "allow_rename", True))
        retag_existing_eff = bool(getattr(args, "retag_existing", True))
        prune_orphans_eff = bool(getattr(args, "prune_orphans", False))
        no_adopt_eff = bool(getattr(args, "no_adopt", False))
        sync_tags_eff = bool(getattr(args, "sync_tags", False))
        cover_art_resize_eff = cfg.cover_art_resize if args.cover_art_resize is None else args.cover_art_resize
        cover_art_max_size_eff = args.cover_art_max_size if args.cover_art_max_size is not None else cfg.cover_art_max_size
        exit_code, _ = cmd_convert_dir(
            args.in_dir,
            args.out_dir,
            codec=codec_eff,
            tvbr=tvbr_eff,
            vbr=vbr_eff,
            opus_vbr_kbps=opus_vbr_kbps_eff,
            workers=workers_eff,
            
            verbose=args.verbose,
            dry_run=args.dry_run,
            force_reencode=force_reencode_eff,
            allow_rename=allow_rename_eff,
            retag_existing=retag_existing_eff,
            prune_orphans=prune_orphans_eff,
            no_adopt=no_adopt_eff,
            sync_tags=sync_tags_eff,
            log_json_path=cfg.log_json,
            pcm_codec=pcm_eff,
            verify_tags=ver_tags_eff,
            verify_strict=ver_strict_eff,
            cover_art_resize=cover_art_resize_eff,
            cover_art_max_size=cover_art_max_size_eff,
        )
        return exit_code
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
