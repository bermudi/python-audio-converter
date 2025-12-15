# Change: Add Library Browser View

## Why
Users need visibility into their library state before running operations. Currently, there's no way to see which files need integrity checks, which are hi-res, which lack compression tags, or which outputs lack PAC_* tags (legacy files). A browser view enables informed decisions about what operations to run.

## What Changes
- Add a "Scan" operation that analyzes the library without modifying anything
- Display scan results in a browsable tree/table view showing file status
- Show per-file indicators: integrity status, bit depth/sample rate, compression level, PAC_* tag presence
- Allow filtering/sorting by status (needs integrity check, hi-res, needs recompress, legacy/adoptable)
- Enable selection of specific files/folders for targeted operations
- Show summary statistics (total files, hi-res count, legacy count, etc.)

## Impact
- Affected specs: library-management
- Affected code: `app/gui/main.py`, new `src/pac/library_scanner.py` module
