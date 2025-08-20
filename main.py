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


def cmd_convert_dir(src_dir: str, out_dir: str, *, tvbr: int, workers: int | None) -> int:
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

    files = scan_flac_files(src_root, compute_flac_md5=False)
    if not files:
        print("No .flac files found")
        return EXIT_OK

    max_workers = workers or (os.cpu_count() or 1)
    pool = WorkerPool(max_workers=max_workers)

    converted = 0
    skipped = 0
    failed = 0

    futures = []
    for sf in files:
        dest_path = out_root / sf.rel_path.with_suffix(".m4a")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            skipped += 1
            continue
        futures.append(
            pool.submit(_encode_one, sf.path, dest_path, tvbr)
        )

    for fut in futures:
        rc = fut.result()
        if rc == 0:
            converted += 1
        else:
            failed += 1

    pool.shutdown()

    total = len(files)
    print(f"Scanned: {total} | Converted: {converted} | Skipped (exists): {skipped} | Failed: {failed}")
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

    args = p.parse_args(argv)
    if args.cmd == "preflight":
        return cmd_preflight()
    if args.cmd == "init-db":
        return cmd_init_db()
    if args.cmd == "convert":
        return cmd_convert(args.src, args.dest, args.tvbr)
    if args.cmd == "convert-dir":
        return cmd_convert_dir(args.in_dir, args.out_dir, tvbr=args.tvbr, workers=args.workers)
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
