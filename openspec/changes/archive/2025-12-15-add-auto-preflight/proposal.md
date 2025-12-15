# Change: Auto-Run Preflight on GUI Startup

## Why
The current GUI requires users to manually click "Preflight" before the Convert tab becomes functional. This creates a confusing UX where Convert/Plan buttons are disabled with no clear indication why, and forces an unnecessary manual step every time the application starts.

## What Changes
- Auto-run preflight check in a background thread when the GUI window initializes
- Show a non-blocking status indicator during preflight (e.g., spinner or "Checking encoders...")
- Enable Convert tab controls immediately upon successful preflight completion
- Cache preflight results for the session to avoid re-running on tab switches
- Remove the manual "Preflight" button from the main UI (or convert it to a "Re-check Encoders" option in a menu/settings)
- Display encoder availability status in a persistent status bar or info panel

## Impact
- Affected specs: `audio-conversion`
- Affected code: `app/gui/main.py` (MainWindow initialization, preflight flow)
