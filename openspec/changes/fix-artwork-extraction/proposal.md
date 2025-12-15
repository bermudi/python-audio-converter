# Change: Fix Artwork Extraction Bugs

## Why
The artwork extraction in `library_planner.py` incorrectly accesses `.data` attribute on already-raw bytes, and the DB migration drops the `outputs` table on every init instead of using incremental migration.

## What Changes
- Fix `library_planner.py`: Use `front_cover` directly instead of `front_cover.data`
- Fix `db.py`: Change `DROP TABLE IF EXISTS outputs` to `CREATE TABLE IF NOT EXISTS outputs`
- Add logging to `ConvertWorker` for debugging

## Impact
- Affected specs: `library-management`
- Affected code: `src/pac/library_planner.py`, `src/pac/db.py`, `app/gui/main.py`
