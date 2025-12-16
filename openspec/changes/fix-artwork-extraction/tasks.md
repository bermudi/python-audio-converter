## 1. Bug Fixes
- [x] 1.1 Fix `front_cover.data` → `front_cover` in `library_planner.py:extract_art()` - Already fixed in codebase; `_first_front_cover()` returns raw bytes
- [x] 1.2 Fix DB migration: `DROP TABLE` → `CREATE TABLE IF NOT EXISTS` in `db.py` - Already uses `CREATE TABLE IF NOT EXISTS`
- [x] 1.3 Add debug logging to `ConvertWorker.run()` in `app/gui/main.py` - Already has logging at start/end

## 2. Validation
- [x] 2.1 Run existing tests to confirm no regressions - Fixed broken test that patched non-existent `extract_art` function; now patches `check_art_extraction_needed`
- [ ] 2.2 Test artwork extraction manually with a FLAC file
