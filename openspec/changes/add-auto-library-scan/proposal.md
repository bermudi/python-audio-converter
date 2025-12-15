# Change: Auto-Scan Library on Path Entry

## Why
Users must manually click "Scan Library" after entering a library path. This extra step feels unnecessary—the natural expectation is that entering a valid path should immediately show the library contents. The current UX creates friction and confusion about whether the path was accepted.

## What Changes
- Auto-trigger library scan when a valid directory path is entered in the Library root field
- Implement debounced path validation (300-500ms delay) to avoid scanning on every keystroke
- Show scan progress inline while loading
- Preserve manual "Scan" button for explicit refresh/rescan
- Support both typed paths and paths selected via file browser dialog
- Clear browser table when path is cleared or becomes invalid

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py` (Library tab, path input handling, BrowserWorker integration)
