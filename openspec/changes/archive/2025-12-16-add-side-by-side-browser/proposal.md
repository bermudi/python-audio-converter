# Change: Add Side-by-Side Browser View

## Why
The current "With Outputs" view crams source and output information into a single row, making it difficult to compare directory structures and see full file paths for both libraries. A side-by-side panel view provides more intuitive visual comparison between FLAC source library and converted mirror.

## What Changes
- Add a new "Side-by-Side" view mode to the Library Browser
- Display two synchronized `QTableView` panels: source (left) and mirror (right)
- Clicking a file in one panel highlights/scrolls to its counterpart in the other
- Visual sync status indicators (matched, missing, orphaned) in both panels
- **BREAKING**: None - existing view modes remain available

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py` (new view mode, split panel layout, selection synchronization)
