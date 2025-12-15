## 1. Spec and UX Alignment
- [ ] 1.1 Confirm Library tab layout matches this change proposal (browser-first, compact operations, settings modal)

## 2. GUI - Layout Refactor
- [ ] 2.1 Refactor Library tab to use a browser-first layout (splitter with compact operations panel + browser)
- [ ] 2.2 Move status counters/issues into a collapsible Details area and auto-expand it during runs

## 3. GUI - Settings Modal
- [ ] 3.1 Implement a modal "Library Settings…" dialog containing existing library settings fields
- [ ] 3.2 Wire settings dialog to persist values using existing settings/config mechanisms

## 4. GUI - Operations Panel
- [ ] 4.1 Replace per-operation "Run" buttons with a compact operations panel (single primary Run + optional per-op quick actions)
- [ ] 4.2 Add operation scope control (Entire Library vs Selection; default to Selection when selection exists)
- [ ] 4.3 Ensure selection-based operations remain available from the browser selection actions/context menu

## 5. Validation
- [ ] 5.1 Manual validation: Library browser table remains usable at typical window size (no excessive scrolling above it)
- [ ] 5.2 Manual validation: operations run successfully on Entire Library and on Selection
- [ ] 5.3 Manual validation: settings dialog updates effective configuration and does not regress existing defaults
