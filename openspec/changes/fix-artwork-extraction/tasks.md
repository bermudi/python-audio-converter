## 1. Bug Fixes
- [ ] 1.1 Fix `front_cover.data` → `front_cover` in `library_planner.py:extract_art()`
- [ ] 1.2 Fix DB migration: `DROP TABLE` → `CREATE TABLE IF NOT EXISTS` in `db.py`
- [ ] 1.3 Add debug logging to `ConvertWorker.run()` in `app/gui/main.py`

## 2. Validation
- [ ] 2.1 Run existing tests to confirm no regressions
- [ ] 2.2 Test artwork extraction manually with a FLAC file
