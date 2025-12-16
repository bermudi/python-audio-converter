## Context
The Library Browser currently offers three view modes (Source Only, With Outputs, Outputs Only) all rendered in a single `QTableView`. The "With Outputs" correlated view shows source files with output status columns, but users cannot see the actual mirror directory structure or easily compare paths side-by-side.

## Goals / Non-Goals
- **Goals**:
  - Provide intuitive visual comparison of source↔mirror libraries
  - Enable synchronized navigation (click one side, see counterpart)
  - Maintain existing view modes as alternatives
- **Non-Goals**:
  - Replacing existing view modes (they remain useful for different workflows)
  - Implementing drag-drop operations between panels
  - Editing/deleting files from the browser

## Decisions

### Decision: QSplitter with two QTableView
Use a `QSplitter` containing two independent `QTableView` widgets sharing a common selection model concept.

**Alternatives considered**:
- Single table with paired columns: Rejected—already implemented as "With Outputs", too cramped
- Tree view with expandable nodes: Rejected—adds complexity, less intuitive for flat comparisons

### Decision: Bidirectional selection sync
When user selects a row in either panel, programmatically select and scroll to the counterpart in the other panel.

**Implementation**: Connect `selectionChanged` signals with guards to prevent infinite loops.

### Decision: Reuse existing scan data
The side-by-side view SHALL use the same `CorrelatedAnalysis` data from `BrowserWorker.MODE_WITH_OUTPUTS`. No new scanning logic needed—just different presentation.

## Risks / Trade-offs
- **Horizontal space**: Side-by-side requires wider window. Mitigation: adjustable splitter, can collapse one panel.
- **Sync complexity**: Selection sync can cause UI flicker. Mitigation: batch updates, use `blockSignals()` during programmatic selection.

## Open Questions
None - all decisions resolved.

## Resolved
- **Linked scrolling**: Enabled by default. Scrolling one panel auto-scrolls the other to keep counterpart files aligned.
