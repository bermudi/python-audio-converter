import sqlite3
import threading
from pathlib import Path
from typing import Optional
from loguru import logger

class PacDB:
    """A resilient history and lookup layer for PAC."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._conn, "connection"):
            self._conn.connection = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.connection.row_factory = sqlite3.Row
            self._conn.connection.execute("PRAGMA foreign_keys = ON;")
            self._conn.connection.execute("PRAGMA journal_mode = WAL;")
            self._conn.connection.execute("PRAGMA synchronous = NORMAL;")
        return self._conn.connection

    def ensure_schema(self):
        """Ensure the database schema is up to date with migrations."""
        # Core tables (CREATE IF NOT EXISTS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS source_files (
                md5 TEXT PRIMARY KEY,
                first_seen_ts INTEGER,
                last_seen_ts INTEGER,
                last_size INTEGER,
                last_mtime_ns INTEGER,
                content_sig_ver INTEGER DEFAULT 1
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS source_paths (
                id INTEGER PRIMARY KEY,
                md5 TEXT REFERENCES source_files(md5) ON DELETE CASCADE,
                rel_path TEXT NOT NULL,
                first_seen_ts INTEGER,
                last_seen_ts INTEGER,
                UNIQUE(md5, rel_path)
            )
        """)
        # Create outputs table if not exists (incremental migration)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                md5 TEXT REFERENCES source_files(md5) ON DELETE CASCADE,
                dest_rel TEXT NOT NULL,
                container TEXT CHECK(container IN ('mp4','opus')) NOT NULL,
                encoder TEXT,
                quality TEXT,
                pac_version TEXT,
                first_seen_ts INTEGER,
                last_seen_ts INTEGER,
                last_size INTEGER,
                last_mtime_ns INTEGER,
                last_seen_had_pac_tags INTEGER DEFAULT 0 CHECK (last_seen_had_pac_tags IN (0,1)),
                UNIQUE(md5, dest_rel)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                ts INTEGER NOT NULL,
                event TEXT NOT NULL,
                md5 TEXT,
                rel_path TEXT,
                dest_rel TEXT,
                details_json TEXT
            )
        """)

        # FLAC library management tables
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS flac_checks (
                md5 TEXT PRIMARY KEY,
                last_test_ts INTEGER,
                test_ok INTEGER,
                test_msg TEXT,
                streaminfo_md5 TEXT,
                bit_depth INTEGER,
                sample_rate INTEGER,
                channels INTEGER
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS flac_policy (
                md5 TEXT PRIMARY KEY,
                compression_level INTEGER,
                last_compress_ts INTEGER,
                compression_tag TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS art_exports (
                md5 TEXT PRIMARY KEY,
                path TEXT,
                last_export_ts INTEGER,
                mime TEXT,
                size INTEGER
            )
        """)

        # Indexes
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_source_paths_rel ON source_paths(rel_path);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_outputs_dest_rel ON outputs(dest_rel);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_outputs_md5 ON outputs(md5);")

        # Schema migrations for existing databases
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(outputs)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Add first_seen_ts if missing
        if 'first_seen_ts' not in columns:
            self.conn.execute("ALTER TABLE outputs ADD COLUMN first_seen_ts INTEGER;")
            from loguru import logger
            logger.info("DB migration: Added first_seen_ts column to outputs table")
        
        # Add last_seen_had_pac_tags if missing
        if 'last_seen_had_pac_tags' not in columns:
            self.conn.execute("ALTER TABLE outputs ADD COLUMN last_seen_had_pac_tags INTEGER DEFAULT 0;")
            self.conn.execute("ALTER TABLE outputs ADD CHECK (last_seen_had_pac_tags IN (0,1));")
            logger.info("DB migration: Added last_seen_had_pac_tags column to outputs table")

        self.conn.commit()

    def begin(self):
        self.conn.execute("BEGIN;")

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def upsert_many_source_files(self, files: list[tuple[str, int, int, int, str, int]]) -> None:
        """Upsert a batch of source files and their paths."""
        self.conn.executemany(
            """INSERT INTO source_files (md5, first_seen_ts, last_seen_ts, last_size, last_mtime_ns)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(md5) DO UPDATE SET
                   last_seen_ts = excluded.last_seen_ts,
                   last_size = excluded.last_size,
                   last_mtime_ns = excluded.last_mtime_ns;""",
            [(f[0], f[1], f[1], f[2], f[3]) for f in files]
        )
        self.conn.executemany(
            """INSERT INTO source_paths (md5, rel_path, first_seen_ts, last_seen_ts)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(md5, rel_path) DO UPDATE SET
                   last_seen_ts = excluded.last_seen_ts;""",
            [(f[0], f[4], f[1], f[1]) for f in files]
        )

    def upsert_many_outputs(self, outputs: list[tuple[str, str, str, str, str, str, int, int, int, bool]]) -> None:
        """Upsert a batch of output files."""
        self.conn.executemany(
            """INSERT INTO outputs (md5, dest_rel, container, encoder, quality, pac_version, first_seen_ts, last_seen_ts, last_size, last_mtime_ns, last_seen_had_pac_tags)
               VALUES (?, ?, ?, ?, ?, ?, COALESCE(first_seen_ts, ?), ?, ?, ?, ?)
               ON CONFLICT(md5, dest_rel) DO UPDATE SET
                   last_seen_ts = excluded.last_seen_ts,
                   last_size = excluded.last_size,
                   last_mtime_ns = excluded.last_mtime_ns,
                   last_seen_had_pac_tags = excluded.last_seen_had_pac_tags;""",
            [
                (
                    o[0] or None, # md5
                    o[1], # dest_rel
                    o[2], # container
                    o[3], # encoder
                    o[4], # quality
                    o[5], # pac_version
                    o[6], # seen_ts for first/last
                    o[7], # size
                    o[8], # mtime_ns
                    o[9], # had_pac_tags
                )
                for o in outputs
            ]
        )

    def lookup_outputs_by_md5(self, md5: str) -> list[sqlite3.Row]:
        """Lookup all outputs for a given MD5."""
        return self.conn.execute("SELECT * FROM outputs WHERE md5 = ?", (md5,)).fetchall()

    def lookup_preferred_output_by_md5(self, md5: str) -> Optional[sqlite3.Row]:
        """Lookup the most recently seen output for a given MD5."""
        return self.conn.execute(
            "SELECT * FROM outputs WHERE md5 = ? ORDER BY last_seen_ts DESC LIMIT 1", (md5,)
        ).fetchone()

    def lookup_output_by_dest_rel(self, dest_rel: str) -> Optional[sqlite3.Row]:
        """Lookup an output by its destination relative path."""
        return self.conn.execute("SELECT * FROM outputs WHERE dest_rel = ?", (dest_rel,)).fetchone()

    def lookup_md5_by_rel_path_history(self, rel_path: str) -> Optional[str]:
        """Lookup an MD5 by a relative path that may have existed in the past."""
        row = self.conn.execute(
            "SELECT md5 FROM source_paths WHERE rel_path = ? ORDER BY last_seen_ts DESC LIMIT 1",
            (rel_path,),
        ).fetchone()
        return row["md5"] if row else None

    def get_source_file_last_seen_ts(self, md5: str) -> Optional[int]:
        """Get the last seen timestamp for a source file."""
        row = self.conn.execute("SELECT last_seen_ts FROM source_files WHERE md5 = ?", (md5,)).fetchone()
        return row["last_seen_ts"] if row else None

    def add_observation(self, event: str, ts: int, md5: str, rel_path: str, dest_rel: str, details_json: str) -> None:
        """Add an observation to the log."""
        self.conn.execute(
            "INSERT INTO observations (event, ts, md5, rel_path, dest_rel, details_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event, ts, md5, rel_path, dest_rel, details_json),
        )

    def update_output_dest_rel(self, old_dest_rel: str, new_dest_rel: str) -> None:
        """Update the destination relative path of an output."""
        self.conn.execute("UPDATE outputs SET dest_rel = ? WHERE dest_rel = ?", (new_dest_rel, old_dest_rel))

    def update_output_tags(self, dest_rel: str, md5: str, encoder: str, quality: str, pac_version: str, source_rel: str) -> None:
        """Update the tags of an output."""
        self.conn.execute(
            """UPDATE outputs SET
                   md5 = ?,
                   encoder = ?,
                   quality = ?,
                   pac_version = ?,
                   last_seen_had_pac_tags = 1
               WHERE dest_rel = ?""",
            (md5, encoder, quality, pac_version, dest_rel),
        )

    def delete_output(self, dest_rel: str) -> None:
        """Delete an output from the database."""
        self.conn.execute("DELETE FROM outputs WHERE dest_rel = ?", (dest_rel,))
