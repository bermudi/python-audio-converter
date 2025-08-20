from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure local src/ is importable when running from project root
ROOT = Path(__file__).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pac.ffmpeg_check import probe_ffmpeg, probe_fdkaac, probe_qaac  # noqa: E402
from pac.encoder import (  # noqa: E402
    build_ffmpeg_cmd,
    run_ffmpeg,
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


def cmd_preflight() -> int:
    st = probe_ffmpeg()
    if not st.available:
        print("ffmpeg: NOT FOUND")
        if st.error:
            print(st.error)
        return EXIT_PREFLIGHT_FAILED
    print(f"ffmpeg: {st.ffmpeg_path}")
    print(f"version: {st.ffmpeg_version}")
    print(f"libfdk_aac (ffmpeg): {'YES' if st.has_libfdk_aac else 'NO'}")

    st_fdk = probe_fdkaac()
    print(f"fdkaac: {'FOUND' if st_fdk.available else 'NOT FOUND'}")
    if st_fdk.available:
        print(f"fdkaac path: {st_fdk.fdkaac_path}")
        if st_fdk.fdkaac_version:
            print(st_fdk.fdkaac_version)

    st_qaac = probe_qaac()
    print(f"qaac: {'FOUND' if st_qaac.available else 'NOT FOUND'}")
    if st_qaac.available:
        print(f"qaac path: {st_qaac.qaac_path}")
        if st_qaac.qaac_version:
            print(st_qaac.qaac_version)

    ok = st.available and (st.has_libfdk_aac or st_fdk.available or st_qaac.available)
    if not ok:
        print("No AAC encoder available. Install ffmpeg with libfdk_aac, or fdkaac, or qaac.")
    return EXIT_OK if ok else EXIT_PREFLIGHT_FAILED


def cmd_init_db() -> int:
    path = pac_db.get_default_db_path()
    conn = pac_db.connect(path)
    conn.close()
    print(f"DB initialized at: {path}")
    return EXIT_OK


def cmd_convert(src: str, dest: str, tvbr: int) -> int:
    src_p = Path(src)
    dest_p = Path(dest)

    st = probe_ffmpeg()
    if not st.available:
        print("ffmpeg not found; cannot convert")
        return EXIT_PREFLIGHT_FAILED

    rc = 1
    if st.has_libfdk_aac:
        cmd = build_ffmpeg_cmd(src_p, dest_p, vbr_quality=5)
        rc = run_ffmpeg(cmd)
    else:
        st_qaac = probe_qaac()
        if st_qaac.available:
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5)
            else:
                print("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                return EXIT_PREFLIGHT_FAILED

    if rc != 0:
        print(f"Encode failed with exit code {rc}")
        return EXIT_WITH_FILE_ERRORS

    # Best-effort tag copy from FLAC -> MP4
    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        print(f"Warning: metadata copy failed: {e}")

    print(f"Wrote: {dest_p}")
    return EXIT_OK


def _encode_one(src_p: Path, dest_p: Path, tvbr: int) -> int:
    """Encode a single file using the same backend selection as cmd_convert()."""
    st = probe_ffmpeg()
    if not st.available:
        print("ffmpeg not found; cannot convert")
        return EXIT_PREFLIGHT_FAILED

    rc = 1
    if st.has_libfdk_aac:
        cmd = build_ffmpeg_cmd(src_p, dest_p, vbr_quality=5)
        rc = run_ffmpeg(cmd)
    else:
        st_qaac = probe_qaac()
        if st_qaac.available:
            rc = run_ffmpeg_pipe_to_qaac(src_p, dest_p, tvbr=tvbr)
        else:
            st_fdk = probe_fdkaac()
            if st_fdk.available:
                rc = run_ffmpeg_pipe_to_fdkaac(src_p, dest_p, vbr_mode=5)
            else:
                print("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
                return EXIT_PREFLIGHT_FAILED

    if rc != 0:
        return rc

    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        print(f"Warning: metadata copy failed: {e}")
    return 0


def _encode_one_selected(src_p: Path, dest_p: Path, *, encoder: str, tvbr: int, vbr: int) -> int:
    """Encode using the preselected backend to keep DB planning consistent.

    encoder: one of "libfdk_aac", "qaac", "fdkaac".
    tvbr: qaac quality scale (e.g., 96 ~ 256 kbps typical).
    vbr: libfdk_aac/fdkaac quality/mode (1..5; 5 ~ 256 kbps typical).
    """
    if encoder == "libfdk_aac":
        cmd = build_ffmpeg_cmd(src_p, dest_p, vbr_quality=vbr)
        rc = run_ffmpeg(cmd)
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
        print(f"Unknown encoder: {encoder}")
        return 1

    try:
        copy_tags_flac_to_mp4(src_p, dest_p)
    except Exception as e:  # pragma: no cover
        print(f"Warning: metadata copy failed: {e}")
    return 0


def cmd_convert_dir(
    src_dir: str,
    out_dir: str,
    *,
    tvbr: int,
    vbr: int,
    workers: int | None,
    hash_streaminfo: bool,
) -> int:
    src_root = Path(src_dir).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Preflight: at least ffmpeg must exist and some encoder available
    st = probe_ffmpeg()
    st_qaac = probe_qaac()
    st_fdk = probe_fdkaac()
    if not (st.available and (st.has_libfdk_aac or st_qaac.available or st_fdk.available)):
        print("No suitable AAC encoder found (need libfdk_aac, qaac, or fdkaac)")
        return EXIT_PREFLIGHT_FAILED

    # Pick encoder once for the whole run (stable planning)
    selected_encoder = "libfdk_aac" if st.has_libfdk_aac else ("qaac" if st_qaac.available else "fdkaac")
    quality_for_db = tvbr if selected_encoder == "qaac" else vbr

    # Scan
    files = scan_flac_files(src_root, compute_flac_md5=hash_streaminfo)
    if not files:
        print("No .flac files found")
        return EXIT_OK

    # DB and plan
    conn = pac_db.connect()
    try:
        db_idx = pac_db.fetch_files_index(conn)
        plan = plan_changes(files, db_idx, vbr_quality=quality_for_db, encoder=selected_encoder)
    finally:
        pass

    to_convert = [pi for pi in plan if pi.decision == "convert"]
    unchanged = [pi for pi in plan if pi.decision == "skip"]

    max_workers = workers or (os.cpu_count() or 1)
    pool = WorkerPool(max_workers=max_workers)

    converted = 0
    failed = 0

    futures = []
    dest_paths: dict[int, tuple[Path, Path]] = {}
    for idx, pi in enumerate(to_convert):
        dest_path = out_root / pi.output_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        futures.append(pool.submit(_encode_one_selected, pi.src_path, dest_path, encoder=selected_encoder, tvbr=tvbr, vbr=vbr))
        dest_paths[idx] = (pi.src_path, dest_path)

    # Collect results and update DB for successes
    for i, fut in enumerate(futures):
        rc = fut.result()
        if rc == 0:
            converted += 1
            pi = to_convert[i]
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
            conn.commit()
        else:
            failed += 1

    pool.shutdown()
    conn.close()

    total = len(plan)
    print(
        f"Planned: {total} | Convert: {len(to_convert)} | Unchanged: {len(unchanged)} | Converted: {converted} | Failed: {failed}"
    )
    return EXIT_OK if failed == 0 else EXIT_WITH_FILE_ERRORS


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python-audio-converter")
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

    args = p.parse_args(argv)
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
        )
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
