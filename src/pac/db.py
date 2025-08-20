"""SQLite state DB helpers (standard library only)."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


APP_DIRNAME = "python-audio-converter"


def get_default_db_path() -> Path:
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
    db_dir = base / APP_DIRNAME
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "state.sqlite"


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_default_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA user_version")
    (ver,) = cur.fetchone()
    if ver == 0:
        _migrate_v0_to_v1(conn)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            src_path TEXT PRIMARY KEY,
            rel_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            flac_md5 TEXT NULL,
            sha256 TEXT NULL,
            duration_ms INTEGER NULL,
            encoder TEXT NOT NULL DEFAULT 'libfdk_aac',
            vbr_quality INTEGER NOT NULL DEFAULT 5,
            container TEXT NOT NULL DEFAULT 'm4a',
            last_converted_at TEXT NULL,
            output_rel TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NULL,
            ffmpeg_version TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            stats_json TEXT NULL
        );

        CREATE TABLE IF NOT EXISTS file_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            src_path TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NULL,
            elapsed_ms INTEGER NULL
        );
        """
    )


def upsert_file(
    conn: sqlite3.Connection,
    *,
    src_path: str,
    rel_path: str,
    size: int,
    mtime_ns: int,
    flac_md5: Optional[str],
    output_rel: str,
    encoder: str = "libfdk_aac",
    vbr_quality: int = 5,
    container: str = "m4a",
) -> None:
    conn.execute(
        """
        INSERT INTO files(src_path, rel_path, size, mtime_ns, flac_md5, output_rel, encoder, vbr_quality, container)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(src_path) DO UPDATE SET
            rel_path=excluded.rel_path,
            size=excluded.size,
            mtime_ns=excluded.mtime_ns,
            flac_md5=excluded.flac_md5,
            output_rel=excluded.output_rel,
            encoder=excluded.encoder,
            vbr_quality=excluded.vbr_quality,
            container=excluded.container
        """,
        (src_path, rel_path, size, mtime_ns, flac_md5, output_rel, encoder, vbr_quality, container),
    )


def fetch_files_index(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM files").fetchall()
    return {row["src_path"]: row for row in rows}
