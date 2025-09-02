from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import time
import threading
from typing import Any, Optional

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
from pac import db as pac_db  # noqa: E402
from pac.scanner import scan_flac_files  # noqa: E402
from pac.scheduler import WorkerPool  # noqa: E402
from pac.planner import plan_changes  # noqa: E402
from pac.config import PacSettings, cli_overrides_from_args  # noqa: E402
from pac.paths import resolve_collisions, sanitize_rel_path  # noqa: E402


EXIT_OK = 0
EXIT_WITH_FILE_ERRORS = 2
EXIT_PREFLIGHT_FAILED = 3


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


def cmd_init_db() -> int:
    path = pac_db.get_default_db_path()
    conn = pac_db.connect(path)
    conn.close()
    logger.info(f"DB initialized at: {path}")
    return EXIT_OK


def cmd_convert(
    src: str,
    dest: str,
    tvbr: int,
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
        rc = encode_with_ffmpeg_libfdk(src_p, dest_p, vbr_quality=5)
    else:
        st_qaac = probe_qaac()
        if st_qaac.available:
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr, pcm_codec=pcm_codec)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5, pcm_codec=pcm_codec)
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
        qual = str(tvbr) if enc == "qaac" else "5"
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


def _encode_one(
    src_p: Path,
    dest_p: Path,
    tvbr: int,
    *,
    pcm_codec: str,
    verify_tags: bool,
    verify_strict: bool,
) -> tuple[int, str]:
    """Encode a single file using the same backend selection as cmd_convert()."""
    st = probe_ffmpeg()
    if not st.available:
        logger.error("ffmpeg not found; cannot convert")
        return EXIT_PREFLIGHT_FAILED

    rc = 1
    if st.has_libfdk_aac:
        rc = encode_with_ffmpeg_libfdk(src_p, dest_p, vbr_quality=5)
    else:
        st_qaac = probe_qaac()
        if st_qaac.available:
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr, pcm_codec=pcm_codec)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5, pcm_codec=pcm_codec)
            else:
                logger.error("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                return EXIT_PREFLIGHT_FAILED

    if rc != 0:
        return rc, "failed"

    # Metadata copy and verification
    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
        logger.bind(action="tags", file=str(src_p.name), status="ok").info("tags copy ok")
    except Exception as e:
        reason = f"copy-exception: {e}"
        logger.bind(action="tags", file=str(src_p.name), status="error", reason=reason).error("tags copy failed")
        if verify_strict:
            return 1, "failed"
        # If not strict, this is a warning. We can't reasonably verify, so we are done with this file.
        return 0, "warn"  # Return success code, but with a warning status.

    # Embed PAC_* tags
    try:
        enc = "libfdk_aac" if probe_ffmpeg().has_libfdk_aac else ("qaac" if probe_qaac().available else ("fdkaac" if probe_fdkaac().available else "aac"))
        qual = "5" if enc in {"libfdk_aac", "fdkaac"} else str(tvbr)
        write_pac_tags_mp4(
            dest_p,
            src_md5="",
            encoder=enc,
            quality=qual,
            version="0.2",
            source_rel=src_p.name,
        )
    except Exception as e:
        logger.bind(action="pac_tags", file=str(src_p.name), status="warn", reason=str(e)).warning("PAC_* embed failed")

    ver_status = "skipped"
    if verify_tags:
        try:
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
            copy_tags_flac_to_opus(src_p, dest_p)
        else:
            copy_tags_flac_to_mp4(src_p, dest_p)
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
    hash_streaminfo: bool,
    verbose: bool,
    dry_run: bool,
    force: bool,
    mode: str,
    commit_batch_size: int,
    log_json_path: Optional[str] = None,
    pcm_codec: str = "pcm_s24le",
    verify_tags: bool = False,
    verify_strict: bool = False,
) -> int:
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
        return EXIT_PREFLIGHT_FAILED

    if codec == "opus":
        if st.has_libopus:
            selected_encoder = "libopus"
        else:
            logger.error("Opus encoding requested, but libopus not found in ffmpeg")
            return EXIT_PREFLIGHT_FAILED
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
                    return EXIT_PREFLIGHT_FAILED

    d_preflight = time.time() - t_preflight_s
    quality_for_db = opus_vbr_kbps if codec == "opus" else (tvbr if selected_encoder == "qaac" else vbr)

    # Scan
    t_scan_s = time.time()
    files = scan_flac_files(src_root, compute_flac_md5=hash_streaminfo)
    d_scan = time.time() - t_scan_s
    if not files:
        logger.info("No .flac files found")
        return EXIT_OK

    # DB and plan
    t_db_s = time.time()
    conn = pac_db.connect()
    try:
        # Reconcile destination: pre-populate DB for sources with existing outputs
        reconciled_srcs: set[Path] = set()
        existing: set[Path] = set()
        if mode == "reconcile":
            # Build set of existing relative output paths under out_root
            for dirpath, _, filenames in os.walk(out_root):
                d = Path(dirpath)
                for fn in filenames:
                    try:
                        rel = (d / fn).relative_to(out_root)
                    except Exception:
                        continue
                    existing.add(rel)
            # Upsert DB entries for sources whose expected output already exists
            for sf in files:
                final_suffix = ".opus" if codec == "opus" else ".m4a"
                out_rel = sanitize_rel_path(sf.rel_path, final_suffix=final_suffix)
                if out_rel in existing:
                    try:
                        pac_db.upsert_file(
                            conn,
                            src_path=str(sf.path),
                            rel_path=str(sf.rel_path),
                            size=sf.size or 0,
                            mtime_ns=sf.mtime_ns or 0,
                            flac_md5=sf.flac_md5,
                            output_rel=str(out_rel),
                            encoder=(
                                "qaac"
                                if selected_encoder == "qaac"
                                else ("fdkaac" if selected_encoder == "fdkaac" else "libfdk_aac")
                            ),
                            vbr_quality=(tvbr if selected_encoder == "qaac" else vbr),
                            container=codec,
                        )
                        reconciled_srcs.add(sf.path)
                    except Exception:
                        pass
            try:
                conn.commit()
            except Exception:
                pass

        db_idx = pac_db.fetch_files_index(conn)
        d_db = time.time() - t_db_s
        t_plan_s = time.time()
        plan = plan_changes(
            files,
            db_idx,
            codec=codec,
            vbr_quality=tvbr if selected_encoder == "qaac" else vbr,
            opus_vbr_kbps=opus_vbr_kbps,
            encoder=selected_encoder,
            force=force,
        )
        d_plan = time.time() - t_plan_s
    finally:
        pass

    to_convert = [pi for pi in plan if pi.decision == "convert"]
    unchanged = [pi for pi in plan if pi.decision == "skip"]


    # Always provide basic run info
    max_workers = workers or (os.cpu_count() or 1)
    quality_str = opus_vbr_kbps if codec == "opus" else (tvbr if selected_encoder == "qaac" else vbr)
    logger.info(
        f"Codec: {codec} | Selected encoder: {selected_encoder} | Quality: {quality_str}"
        f" | PCM: {pcm_codec} | Workers: {max_workers} | Hash: {'on' if hash_streaminfo else 'off'}"
        f" | Force: {'on' if force else 'off'} | Mode: {mode}"
    )
    # Show encoder binary path for transparency
    if selected_encoder == "libfdk_aac":
        logger.info(f"Encoder path: ffmpeg -> {st.ffmpeg_path}")
    elif selected_encoder == "qaac" and st_qaac is not None and getattr(st_qaac, 'qaac_path', None):
        logger.info(f"Encoder path: qaac -> {st_qaac.qaac_path}")
    elif selected_encoder == "fdkaac" and st_fdk is not None and getattr(st_fdk, 'fdkaac_path', None):
        logger.info(f"Encoder path: fdkaac -> {st_fdk.fdkaac_path}")
    logger.info(f"Source: {src_root} -> Dest: {out_root}")
    logger.info(f"Planned: {len(plan)} | Convert: {len(to_convert)} | Unchanged: {len(unchanged)}")

    # Concise plan breakdown by change reason
    if plan:
        if force:
            logger.info(f"Plan breakdown: forced={len(to_convert)}")
        else:
            not_in_db = 0
            changed_size = 0
            changed_mtime = 0
            changed_md5 = 0
            changed_quality = 0
            changed_encoder = 0
            for pi in plan:
                if pi.decision == "skip":
                    continue
                if pi.reason == "not in DB":
                    not_in_db += 1
                elif pi.reason.startswith("changed: "):
                    parts = [p.strip() for p in pi.reason[len("changed: "):].split(",")]
                    for p in parts:
                        if p == "size":
                            changed_size += 1
                        elif p == "mtime":
                            changed_mtime += 1
                        elif p == "md5":
                            changed_md5 += 1
                        elif p == "quality":
                            changed_quality += 1
                        elif p == "encoder":
                            changed_encoder += 1
        if not force:
            if any([not_in_db, changed_size, changed_mtime, changed_md5, changed_quality, changed_encoder]):
                logger.info(
                    "Plan breakdown: "
                    + f"new={not_in_db} "
                    + f"size={changed_size} mtime={changed_mtime} md5={changed_md5} "
                    + f"quality={changed_quality} encoder={changed_encoder}"
                )

    # Prepare run settings and insert run row before any file rows
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    settings = {
        "source": str(src_root),
        "dest": str(out_root),
        "codec": codec,
        "encoder": selected_encoder,
        "quality": quality_for_db,
        "pcm_codec": pcm_codec,
        "workers": max_workers,
        "hash": bool(hash_streaminfo),
        "force": bool(force),
        "mode": mode,
        "ffmpeg_path": getattr(st, "ffmpeg_path", None),
        "ffmpeg_version": getattr(st, "ffmpeg_version", None),
        "qaac_version": getattr(st_qaac, "qaac_version", None) if st_qaac is not None else None,
        "fdkaac_version": getattr(st_fdk, "fdkaac_version", None) if st_fdk is not None else None,
    }
    run_id = pac_db.insert_run(conn, started_at=started_iso, ffmpeg_version=getattr(st, "ffmpeg_version", None), settings=settings)
    conn.commit()

    # Dry-run: show planned actions and exit without encoding
    if dry_run:
        logger.info("Plan details:")
        for pi in plan:
            if pi.decision == "convert":
                logger.info(f"CONVERT  {pi.rel_path} -> {pi.output_rel} | {pi.reason}")
            else:
                logger.info(f"SKIP     {pi.rel_path} | {pi.reason}")
        # Record skipped files in DB for audit even in dry-run as per tracking (status=skipped)
        try:
            for pi in plan:
                if pi.decision == "skip":
                    pac_db.insert_file_run(
                        conn,
                        run_id=run_id,
                        src_path=str(pi.src_path),
                        status="skipped",
                        reason=("reconciled" if (mode == "reconcile" and 'reconciled_srcs' in locals() and pi.src_path in reconciled_srcs) else pi.reason),
                        elapsed_ms=None,
                    )
            pac_db.finish_run(
                conn,
                run_id,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                stats={
                    "planned": len(plan),
                    "to_convert": len(to_convert),
                    "unchanged": len(unchanged),
                    "converted": 0,
                    "failed": 0,
                },
            )
            conn.commit()
        except Exception:
            pass
        return EXIT_OK

    if verbose:
        logger.debug(
            "Preflight: ffmpeg probe = "
            + f"{d_probe_ff:.3f}s"
            + (f", qaac probe = {d_probe_qa:.3f}s" if 'd_probe_qa' in locals() else "")
            + (f", fdkaac probe = {d_probe_fd:.3f}s" if 'd_probe_fd' in locals() else "")
        )
        logger.debug(f"Scan: {len(files)} files in {d_scan:.3f}s | DB: {d_db:.3f}s | Plan: {d_plan:.3f}s")

    pool = WorkerPool(max_workers=max_workers)

    converted = 0
    failed = 0

    t_encode_s = time.time()
    # Verification counters
    ver_checked = 0
    ver_ok = 0
    ver_warn = 0
    ver_failed = 0

    # Collect results as they complete and update DB for successes
    total_bytes = 0
    done = 0
    since_commit = 0

    # Optional: sync-tags mode processes unchanged items with tag copy + verify
    tag_sync_processed = 0
    tag_sync_ok = 0
    tag_sync_warn = 0
    tag_sync_failed = 0

    if mode == "force-rebuild" and not dry_run:
        # Safety confirmation
        try:
            prompt = f"Force rebuild will re-encode {len(plan)} files. Continue? [y/N]: "
            resp = input(prompt)
            if str(resp).strip().lower() not in {"y", "yes"}:
                logger.warning("Force rebuild cancelled by user")
                pac_db.finish_run(
                    conn,
                    run_id,
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    stats={
                        "planned": len(plan),
                        "to_convert": len(to_convert),
                        "unchanged": len(unchanged),
                        "converted": 0,
                        "failed": 0,
                    },
                )
                conn.commit()
                return EXIT_OK
        except Exception:
            pass

    if mode == "sync-tags":
        bound = max(1, max_workers * 2)
        stop_event = threading.Event()

        def _tag_task(pi):
            dp = out_root / pi.output_rel
            t0 = time.time()
            try:
                if codec == "opus":
                    copy_tags_flac_to_opus(pi.src_path, dp)
                else:
                    copy_tags_flac_to_mp4(pi.src_path, dp)
                disc = []
                status = "ok"
                if verify_tags:
                    try:
                        if codec == "opus":
                            disc = verify_tags_flac_vs_opus(pi.src_path, dp)
                        else:
                            disc = verify_tags_flac_vs_mp4(pi.src_path, dp)
                    except Exception as e:
                        disc = [f"verify-exception: {e}"]
                    status = "ok" if not disc else ("failed" if verify_strict else "warn")
                return (pi, 0, int((time.time() - t0) * 1000), status, disc)
            except Exception as e:
                return (pi, 1, int((time.time() - t0) * 1000), "failed", [f"exception: {e}"])

        for pi, rc_ms_status in pool.imap_unordered_bounded(_tag_task, unchanged, max_pending=bound, stop_event=stop_event):
            # Unpack
            _, rc, elapsed_ms, status, disc = rc_ms_status if isinstance(rc_ms_status, tuple) else (None, 1, 0, "failed", ["bad-return"])
            tag_sync_processed += 1
            try:
                reason = f"sync-tags: {status}" + (f" | {', '.join(disc)}" if disc else "")
                pac_db.insert_file_run(
                    conn,
                    run_id=run_id,
                    src_path=str(pi.src_path),
                    status="skipped",
                    reason=reason,
                    elapsed_ms=elapsed_ms,
                )
                since_commit += 1
            except Exception:
                pass
            if status == "ok":
                tag_sync_ok += 1
            elif status == "warn":
                tag_sync_warn += 1
            else:
                tag_sync_failed += 1
            if since_commit >= max(1, commit_batch_size):
                try:
                    conn.commit()
                    since_commit = 0
                except Exception:
                    pass
        # After processing, do not double-insert skipped entries for unchanged
    else:
        # Persist skipped items (unchanged) as file_runs
        for pi in unchanged:
            try:
                pac_db.insert_file_run(
                    conn,
                    run_id=run_id,
                    src_path=str(pi.src_path),
                    status="skipped",
                    reason=("reconciled" if (mode == "reconcile" and 'reconciled_srcs' in locals() and pi.src_path in reconciled_srcs) else pi.reason),
                    elapsed_ms=None,
                )
                since_commit += 1
            except Exception:
                pass
        if since_commit:
            try:
                conn.commit()
                since_commit = 0
            except Exception:
                pass
    # In sync-tags mode, do not perform any re-encoding; mark would-be converts as skipped.
    if mode == "sync-tags":
        for pi in to_convert:
            try:
                pac_db.insert_file_run(
                    conn,
                    run_id=run_id,
                    src_path=str(pi.src_path),
                    status="skipped",
                    reason="sync-tags: no-encode",
                    elapsed_ms=None,
                )
                since_commit += 1
            except Exception:
                pass
        if since_commit:
            try:
                conn.commit()
                since_commit = 0
            except Exception:
                pass
        # Prevent the encoding loop from running any work
        to_convert = []
    # In reconcile mode, only convert missing outputs; skip items whose output already exists
    elif mode == "reconcile":
        if 'existing' in locals() and existing:
            still_convert = []
            for pi in to_convert:
                try:
                    if Path(pi.output_rel) in existing:
                        pac_db.insert_file_run(
                            conn,
                            run_id=run_id,
                            src_path=str(pi.src_path),
                            status="skipped",
                            reason="reconcile: existing-output",
                            elapsed_ms=None,
                        )
                        since_commit += 1
                    else:
                        still_convert.append(pi)
                except Exception:
                    still_convert.append(pi)
            if since_commit:
                try:
                    conn.commit()
                    since_commit = 0
                except Exception:
                    pass
            to_convert = still_convert
    # Bounded processing via WorkerPool to keep <= ~2x workers in flight
    bound = max(1, max_workers * 2)
    stop_event = threading.Event()  # Hook for future GUI pause/cancel

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
        )

    for pi, res in pool.imap_unordered_bounded(_task, to_convert, max_pending=bound, stop_event=stop_event):
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
            # Upsert DB for successful encode
            try:
                pac_db.upsert_file(
                    conn,
                    src_path=str(pi.src_path),
                    rel_path=str(pi.rel_path),
                    size=pi.size or 0,
                    mtime_ns=pi.mtime_ns or 0,
                    flac_md5=pi.flac_md5,
                    output_rel=str(pi.output_rel),
                    encoder=pi.encoder,
                    vbr_quality=pi.vbr_quality,
                    container=codec,
                )
                since_commit += 1
            except Exception:
                pass
            # file_runs: converted
            try:
                pac_db.insert_file_run(
                    conn,
                    run_id=run_id,
                    src_path=str(pi.src_path),
                    status="converted",
                    reason=pi.reason,
                    elapsed_ms=int(elapsed_s * 1000),
                )
                since_commit += 1
            except Exception:
                pass
            if since_commit >= max(1, commit_batch_size):
                conn.commit()
                since_commit = 0
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
            # file_runs: failed
            try:
                pac_db.insert_file_run(
                    conn,
                    run_id=run_id,
                    src_path=str(pi.src_path),
                    status="failed",
                    reason=pi.reason,
                    elapsed_ms=int(elapsed_s * 1000),
                )
                since_commit += 1
                if since_commit >= max(1, commit_batch_size):
                    conn.commit()
                    since_commit = 0
            except Exception:
                pass

    # Final commit for any remaining batched operations
    try:
        if since_commit > 0:
            conn.commit()
    except Exception:
        pass
    pool.shutdown()
    # Finish run
    try:
        pac_db.finish_run(
            conn,
            run_id,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            stats={
                "planned": len(plan),
                "to_convert": len(to_convert),
                "unchanged": len(unchanged),
                "converted": converted,
                "failed": failed,
            },
        )
        conn.commit()
    except Exception:
        pass
    conn.close()
    d_encode = time.time() - t_encode_s

    total = len(plan)
    logger.info(
        f"Planned: {total} | Convert: {len(to_convert)} | Unchanged: {len(unchanged)} | Converted: {converted} | Failed: {failed}"
    )
    # Always print concise timing summary
    d_total = time.time() - t_preflight_s
    logger.info(
        f"Timing: total={d_total:.3f}s preflight={d_preflight:.3f}s scan={d_scan:.3f}s db={d_db:.3f}s plan={d_plan:.3f}s encode={d_encode:.3f}s"
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
        "quality": quality_for_db,
        "workers": max_workers,
        "hash": bool(hash_streaminfo),
        "force": bool(force),
        "mode": mode,
        "counts": {
            "planned": total,
            "to_convert": len(to_convert),
            "unchanged": len(unchanged),
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
        "tag_sync": {
            "processed": int(tag_sync_processed),
            "ok": int(tag_sync_ok),
            "warn": int(tag_sync_warn),
            "failed": int(tag_sync_failed),
        } if mode == "sync-tags" else None,
        "timing_s": {
            "total": round(d_total, 3),
            "preflight": round(d_preflight, 3),
            "scan": round(d_scan, 3),
            "db": round(d_db, 3),
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
    return EXIT_OK if failed == 0 else EXIT_WITH_FILE_ERRORS


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
    sub.add_parser("init-db", help="Initialize local state database")

    p_convert = sub.add_parser(
        "convert",
        help="Convert a single source file to M4A (tvbr by default)",
    )
    p_convert.add_argument("src", help="Input audio file (e.g., FLAC)")
    p_convert.add_argument("dest", help="Output .m4a path")
    p_convert.add_argument(
        "--tvbr",
        type=int,
        default=96,
        help="qaac true VBR value targeting around 256 kbps (default: 96)",
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
    # Tri-state hash flag: default None, explicit --hash/--no-hash set True/False
    hash_group = p_dir.add_mutually_exclusive_group()
    hash_group.add_argument(
        "--hash",
        dest="hash_streaminfo",
        action="store_const",
        const=True,
        default=None,
        help="Compute and store FLAC STREAMINFO MD5 for change detection (slower)",
    )
    hash_group.add_argument(
        "--no-hash",
        dest="hash_streaminfo",
        action="store_const",
        const=False,
        help="Disable FLAC STREAMINFO MD5 (use size+mtime only)",
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
    mode_group = p_dir.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--force",
        action="store_true",
        help="Re-encode all scanned files regardless of DB state (deprecated; use --mode force-rebuild)",
    )
    mode_group.add_argument(
        "--mode",
        dest="mode",
        choices=["incremental", "reconcile", "sync-tags", "force-rebuild"],
        default=None,
        help="Operation mode: incremental (default), reconcile destination, sync-tags, or force-rebuild",
    )
    p_dir.add_argument(
        "--commit-batch-size",
        type=int,
        default=None,
        help="Batch DB commits per N successful files (default from settings)",
    )
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
    if args.cmd == "init-db":
        return cmd_init_db()
    if args.cmd == "convert":
        tvbr_eff = args.tvbr if args.tvbr is not None else cfg.tvbr
        pcm_eff = args.pcm_codec if getattr(args, "pcm_codec", None) is not None else cfg.pcm_codec
        ver_tags_eff = bool(args.verify_tags) or bool(cfg.verify_tags)
        ver_strict_eff = bool(args.verify_strict) or bool(cfg.verify_strict)
        return cmd_convert(
            args.src,
            args.dest,
            tvbr_eff,
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
        hash_eff = cfg.hash_streaminfo if args.hash_streaminfo is None else args.hash_streaminfo
        commit_eff = args.commit_batch_size if args.commit_batch_size is not None else cfg.commit_batch_size
        pcm_eff = args.pcm_codec if getattr(args, "pcm_codec", None) is not None else cfg.pcm_codec
        ver_tags_eff = bool(args.verify_tags) or bool(cfg.verify_tags)
        ver_strict_eff = bool(args.verify_strict) or bool(cfg.verify_strict)
        # Derive effective mode and force: --mode overrides legacy --force; fall back to config
        if getattr(args, "mode", None):
            mode_eff = args.mode
            force_eff = True if args.mode == "force-rebuild" else False
        else:
            if args.force or cfg.force:
                mode_eff = "force-rebuild"
                force_eff = True
            else:
                mode_eff = getattr(cfg, "mode", "incremental")
                force_eff = True if mode_eff == "force-rebuild" else False
        return cmd_convert_dir(
            args.in_dir,
            args.out_dir,
            codec=codec_eff,
            tvbr=tvbr_eff,
            vbr=vbr_eff,
            opus_vbr_kbps=opus_vbr_kbps_eff,
            workers=workers_eff,
            hash_streaminfo=hash_eff,
            verbose=args.verbose,
            dry_run=args.dry_run,
            force=force_eff,
            mode=mode_eff,
            commit_batch_size=commit_eff,
            log_json_path=cfg.log_json,
            pcm_codec=pcm_eff,
            verify_tags=ver_tags_eff,
            verify_strict=ver_strict_eff,
        )
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
