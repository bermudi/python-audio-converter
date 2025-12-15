# Change: Add Dual-Library Browser View

## Why
The Library tab has two path inputs (FLAC source library and Mirror output), but the browser only shows files from one directory at a time. Users cannot see the relationship between source FLAC files and their converted outputs—critical for understanding sync status, finding orphans, and identifying files needing conversion. This makes the Library tab less useful for its primary purpose: managing the source↔output relationship.

## What Changes
- Add a correlated view mode showing source files alongside their output status
- Display conversion status per source file: converted, outdated, missing, orphan
- Enable filtering by sync status (e.g., "show only files needing conversion")
- Show output file details (codec, quality, PAC_* tags) inline with source
- Support switching between "Source View" (current) and "Correlated View" (new)
- Add output-focused view showing orphan outputs without sources

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py`, `src/pac/library_analyzer.py`
