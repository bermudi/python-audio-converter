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

from pac.ffmpeg_check import probe_ffmpeg  # noqa: E402
from pac import db as pac_db  # noqa: E402


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
    print(f"libfdk_aac: {'YES' if st.has_libfdk_aac else 'NO'}")
    return EXIT_OK if st.has_libfdk_aac else EXIT_PREFLIGHT_FAILED


def cmd_init_db() -> int:
    path = pac_db.get_default_db_path()
    conn = pac_db.connect(path)
    conn.close()
    print(f"DB initialized at: {path}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python-audio-converter")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="Check ffmpeg and libfdk_aac availability")
    sub.add_parser("init-db", help="Initialize local state database")

    args = p.parse_args(argv)
    if args.cmd == "preflight":
        return cmd_preflight()
    if args.cmd == "init-db":
        return cmd_init_db()
    p.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
