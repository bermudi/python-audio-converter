# Change: Refactor Library Tab Layout (Browser-First)

## Why
The current Library tab stacks Operations, Library Settings, status counters, and the Library Browser vertically. On typical window sizes, Operations and Settings consume most of the vertical space, leaving the browser (the user’s primary decision-making surface) cramped.

## What Changes
- Reorganize the Library tab around a browser-first layout so the table view remains usable at typical window heights.
- Replace the always-visible "Library Settings" group with a modal "Library Settings…" dialog.
- Replace per-operation "Run" buttons with a compact operations panel:
  - Select operations via toggles/checkboxes.
  - Provide a single primary "Run" action plus an overflow menu for one-off runs.
- Add explicit operation scope control:
  - Run operations on either the entire library or the current browser selection.
  - Default to selection when a selection exists.
- Move status counters and issues into a collapsible "Details" area that can auto-expand while an operation is running.

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py` (Library tab layout and dialogs)
