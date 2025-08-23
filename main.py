from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import time
from concurrent.futures import as_completed
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
)
from pac.metadata import copy_tags_flac_to_mp4  # noqa: E402
from pac import db as pac_db  # noqa: E402
from pac.scanner import scan_flac_files  # noqa: E402
from pac.scheduler import WorkerPool  # noqa: E402
from pac.planner import plan_changes  # noqa: E402


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


def cmd_convert(src: str, dest: str, tvbr: int) -> int:
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
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5)
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
    logger.info(f"Wrote: {dest_p}")
    return EXIT_OK


def _encode_one(src_p: Path, dest_p: Path, tvbr: int) -> int:
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
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5)
            else:
                logger.error("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                return EXIT_PREFLIGHT_FAILED

    if rc != 0:
        return rc

    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Metadata copy failed: {e}")
    return 0


def _encode_one_selected(src_p: Path, dest_p: Path, *, encoder: str, tvbr: int, vbr: int) -> int:
    """Encode using the preselected backend to keep DB planning consistent.

    encoder: one of "libfdk_aac", "qaac", "fdkaac".
    tvbr: qaac quality scale (e.g., 96 ~ 256 kbps typical).
    vbr: libfdk_aac/fdkaac quality/mode (1..5; 5 ~ 256 kbps typical).
    """
    if encoder == "libfdk_aac":
        rc = encode_with_ffmpeg_libfdk(src_p, dest_p, vbr_quality=vbr)
        if rc != 0:
            return rc
    elif encoder == "qaac":
        rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr)
        if rc != 0:
            return rc
    elif encoder == "fdkaac":
        rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=vbr)
        if rc != 0:
            return rc
    else:  # pragma: no cover - defensive
        logger.error(f"Unknown encoder: {encoder}")
        return 1

    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Metadata copy failed: {e}")
    return 0


def _encode_one_selected_timed(src_p: Path, dest_p: Path, *, encoder: str, tvbr: int, vbr: int) -> tuple[int, float]:
    """Wrapper that measures wall time for a single encode."""
    t0 = time.time()
    rc = _encode_one_selected(src_p, dest_p, encoder=encoder, tvbr=tvbr, vbr=vbr)
    return rc, time.time() - t0


def cmd_convert_dir(
    src_dir: str,
    out_dir: str,
    *,
    tvbr: int,
    vbr: int,
    workers: int | None,
    hash_streaminfo: bool,
    verbose: bool,
    dry_run: bool,
    force: bool,
    commit_batch_size: int,
    log_json_path: Optional[str] = None,
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
    quality_for_db = tvbr if selected_encoder == "qaac" else vbr

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
        db_idx = pac_db.fetch_files_index(conn)
        d_db = time.time() - t_db_s
        t_plan_s = time.time()
        plan = plan_changes(files, db_idx, vbr_quality=quality_for_db, encoder=selected_encoder, force=force)
        d_plan = time.time() - t_plan_s
    finally:
        pass

    to_convert = [pi for pi in plan if pi.decision == "convert"]
    unchanged = [pi for pi in plan if pi.decision == "skip"]

    # Always provide basic run info
    max_workers = workers or (os.cpu_count() or 1)
    logger.info(
        f"Selected encoder: {selected_encoder} | Quality: "
        f"{(tvbr if selected_encoder=='qaac' else vbr)}"
        f" | Workers: {max_workers} | Hash: {'on' if hash_streaminfo else 'off'}"
        f" | Force: {'on' if force else 'off'}"
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
        "encoder": selected_encoder,
        "quality": tvbr if selected_encoder == "qaac" else vbr,
        "workers": max_workers,
        "hash": bool(hash_streaminfo),
        "force": bool(force),
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
                        reason=pi.reason,
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
    future_to: dict[Any, tuple] = {}
    for pi in to_convert:
        dest_path = out_root / pi.output_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        fut = pool.submit(_encode_one_selected_timed, pi.src_path, dest_path, encoder=selected_encoder, tvbr=tvbr, vbr=vbr)
        future_to[fut] = (pi, dest_path)

    # Collect results as they complete and update DB for successes
    total_bytes = 0
    done = 0
    since_commit = 0

    # First, persist all skipped items as file_runs (status=skipped)
    for pi in unchanged:
        try:
            pac_db.insert_file_run(
                conn,
                run_id=run_id,
                src_path=str(pi.src_path),
                status="skipped",
                reason=pi.reason,
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
    for fut in as_completed(future_to):
        pi, dest_path = future_to[fut]
        rc, elapsed_s = fut.result()
        done += 1
        if rc == 0:
            converted += 1
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
                container="m4a",
            )
            since_commit += 1
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
        "encoder": selected_encoder,
        "quality": tvbr if selected_encoder == "qaac" else vbr,
        "workers": max_workers,
        "hash": bool(hash_streaminfo),
        "force": bool(force),
        "counts": {
            "planned": total,
            "to_convert": len(to_convert),
            "unchanged": len(unchanged),
            "converted": converted,
            "failed": failed,
        },
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
    p.add_argument(
        "--log-level",
        default="INFO",
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

    p_dir = sub.add_subparser if False else sub.add_parser(  # keep structure simple
        "convert-dir",
        help="Batch convert a source directory of .flac files to a destination tree",
    )
    p_dir.add_argument("--in", dest="in_dir", required=True, help="Source directory containing .flac files")
    p_dir.add_argument("--out", dest="out_dir", required=True, help="Destination root directory for .m4a outputs")
    p_dir.add_argument(
        "--workers",
        type=int,
        default=(os.cpu_count() or 1),
        help="Parallel workers (default: number of CPU cores)",
    )
    p_dir.add_argument(
        "--tvbr",
        type=int,
        default=96,
        help="qaac true VBR value targeting around 256 kbps (default: 96)",
    )
    p_dir.add_argument(
        "--vbr",
        type=int,
        default=5,
        help="libfdk_aac/fdkaac VBR quality/mode 1..5 (default: 5 ~ 256 kbps)",
    )
    p_dir.add_argument(
        "--hash",
        dest="hash_streaminfo",
        action="store_true",
        help="Compute and store FLAC STREAMINFO MD5 for change detection (slower)",
    )
    p_dir.add_argument(
        "--no-hash",
        dest="hash_streaminfo",
        action="store_false",
        help="Disable FLAC STREAMINFO MD5 (use size+mtime only)",
    )
    p_dir.set_defaults(hash_streaminfo=False)
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
    p_dir.add_argument(
        "--force",
        action="store_true",
        help="Re-encode all scanned files regardless of DB state",
    )
    p_dir.add_argument(
        "--commit-batch-size",
        type=int,
        default=32,
        help="Batch DB commits per N successful files (default: 32)",
    )

    args = p.parse_args(argv)
    # Configure logging early
    configure_logging(args.log_level, args.log_json)
    if args.cmd == "preflight":
        return cmd_preflight()
    if args.cmd == "init-db":
        return cmd_init_db()
    if args.cmd == "convert":
        return cmd_convert(args.src, args.dest, args.tvbr)
    if args.cmd == "convert-dir":
        return cmd_convert_dir(
            args.in_dir,
            args.out_dir,
            tvbr=args.tvbr,
            vbr=args.vbr,
            workers=args.workers,
            hash_streaminfo=args.hash_streaminfo,
            verbose=args.verbose,
            dry_run=args.dry_run,
            force=args.force,
            commit_batch_size=args.commit_batch_size,
            log_json_path=args.log_json,
        )
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
