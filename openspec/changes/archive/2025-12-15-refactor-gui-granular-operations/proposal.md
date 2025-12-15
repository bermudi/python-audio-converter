# Change: Refactor GUI for Granular Library Operations

## Why
The current Library tab has a single "Run Library Maintenance" button that executes all phases (integrity check, resample, recompress, artwork extraction) at once. Users need granular control to run individual operations, especially when dealing with large libraries or troubleshooting specific files.

## What Changes
- **BREAKING**: Remove monolithic "Run Library Maintenance" button
- Split library operations into discrete actions the user can trigger independently
- Add operation selection (checkboxes or separate buttons) for: Scan, Integrity Check, Resample, Recompress, Extract Artwork, Adopt Legacy Files
- Allow running operations on selected files or entire library
- Keep dry-run capability per operation
- Add "Adopt Legacy Files" as explicit operation for files from older PAC versions without PAC_* tags

## Impact
- Affected specs: library-management
- Affected code: `app/gui/main.py`, `src/pac/library_runner.py`
