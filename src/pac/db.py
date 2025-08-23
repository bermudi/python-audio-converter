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
    # Migration: v1 -> v2 adds constraints and indexes
    cur = conn.execute("PRAGMA user_version")
    (ver,) = cur.fetchone()
    if ver == 1:
        _migrate_v1_to_v2(conn)
        conn.execute("PRAGMA user_version = 2")
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


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add CHECK constraint on file_runs.status and create indexes.

    SQLite cannot add a CHECK to an existing column via ALTER TABLE, so we
    recreate the table and copy data.
    """
    conn.executescript(
        """
        PRAGMA foreign_keys=off;
        BEGIN TRANSACTION;

        -- Recreate file_runs with CHECK constraint
        CREATE TABLE IF NOT EXISTS file_runs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            src_path TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('converted','skipped','failed')),
            reason TEXT NULL,
            elapsed_ms INTEGER NULL
        );

        INSERT INTO file_runs_new(id, run_id, src_path, status, reason, elapsed_ms)
        SELECT id, run_id, src_path, status, reason, elapsed_ms FROM file_runs;

        DROP TABLE file_runs;
        ALTER TABLE file_runs_new RENAME TO file_runs;

        -- Useful indexes
        CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
        CREATE INDEX IF NOT EXISTS idx_file_runs_run_id ON file_runs(run_id);
        CREATE INDEX IF NOT EXISTS idx_file_runs_src_path ON file_runs(src_path);

        COMMIT;
        PRAGMA foreign_keys=on;
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


# --- Run/file_run helpers ---------------------------------------------------

def insert_run(
    conn: sqlite3.Connection,
    *,
    started_at: str,
    ffmpeg_version: str | None,
    settings: dict,
) -> int:
    """Insert a row into runs and return its id.

    settings is serialized to JSON.
    """
    cur = conn.execute(
        "INSERT INTO runs(started_at, finished_at, ffmpeg_version, settings_json, stats_json) VALUES(?,?,?,?,?)",
        (started_at, None, ffmpeg_version or "", json.dumps(settings, sort_keys=True), None),
    )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    finished_at: str,
    stats: dict | None = None,
) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
        (finished_at, json.dumps(stats, sort_keys=True) if stats is not None else None, run_id),
    )


def insert_file_run(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    src_path: str,
    status: str,
    reason: str | None,
    elapsed_ms: int | None,
) -> int:
    """Insert a file_runs row and return its id.

    status must be one of 'converted','skipped','failed'.
    """
    cur = conn.execute(
        "INSERT INTO file_runs(run_id, src_path, status, reason, elapsed_ms) VALUES(?,?,?,?,?)",
        (run_id, src_path, status, reason, elapsed_ms),
    )
    return int(cur.lastrowid)
